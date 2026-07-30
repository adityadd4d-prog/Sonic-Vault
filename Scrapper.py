import httpx
from google import genai
from google.genai import errors, types
import time
from pydantic import BaseModel, Field
from pathlib import Path
import csv
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

IEM_TAGS = (
        "Dynamic Driver", "Balanced Armature", "Planar Magnetic", "Electrostatic", "Hybrid", "Tribrid",
        "Neutral", "Warm", "Bright", "Dark", "V Shaped", "U Shaped", "Basshead", "Mid Forward", "Harman Target",
        "Stage Monitor", "Studio Reference", "Casual Listening", "Gaming", "Sports", "Sleep Friendly", "ANC",
        "Detachable Cable", "MMCX", "2 Pin", "Wireless TWS", "Balanced Cable Included", "Tuning Switches",
        "Quadbrid", "Pentabrid", "Hexabrid"
    )

class IemDetails(BaseModel):
    search_name: str = Field(description="The Searched iem to which this details belong. Do not make any change to the searched keyword in any form. Anything Written in parentheses should be retained as is.")
    brand: str = Field(description="The Name of the Brand to which the IEM belongs. Keep the Brand name the same with which the company is Registered")
    name: str = Field(description="The Model name of the iem")
    driver: str = Field(description="The Driver Setup of the Iem. Example : 1DD + 2BA, 2DD + 2BA")
    anc: str = Field(description="Tell Either ANC is available or NOT and if available what is the DB level")
    freq_range: str = Field(description="The frequency range upto which the iem can produce sound. Example : 20Hz - 20KHz, 20Hz - 40KHz")
    impedance: str = Field(description="The impedance of the iem in ohms, must include the word ohms")
    connector_type: str = Field(description="The Type of connector used in the iem, Must be one of : 0.75mm 2Pin, 0.78mm 2Pin or MMCX")
    signature: str = Field(description="One Line Description about how the iem sounds")
    mrp: float = Field(description="The Retail Price set by the manufacturer in USD. Don't include The word USD keep it strictly in float only, price can't be zero")
    tags: str = Field(description=f"Use as many Suitable tags from the given list as applicable : {IEM_TAGS}")


class IemResponse(BaseModel):
    results: list[IemDetails] = Field(description="A list Containing the details of the requested IEM")


class DetailFetcherThread:
    def __init__(self, api_key, job_queue, detail_queue):
        self.try_cnt = 0
        self.MAX_TRIES = 15
        self.FAIL_THRESHOLD = 7
        self.api_key =  api_key
        self.job_queue = job_queue
        self.detail_queue = detail_queue
        self._json_parser_config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=IemResponse.model_json_schema(),
            temperature=0.1,
            system_instruction="You are a JSON Parser. Take the given information and parse it to proper JSON as per the given JSON Schema"
        )
        self._detail_fetcher_config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.1,
            system_instruction=f"""You are a Web Scrapper. Your Function is to scrap the internet for details regarding IEM.
             The response should contain The given information for each iem :
             search name i.e. the exact name of the IEM with which it is searched for, there should be no change in it and anything written in parentheses should be retained as is,
             brand name with which the company is registered,
             model name of the iem,
             driver configuration of the iem, 
             the frequency range upto which it can produce sound,
             impedance of the iem, must be in ohms and include the word 'ohm',
             connector type of the iem,
             summary about the sound signature of the iem,
             the maximum retail price set by the manufacturer : it can not be zero, if found to zero search for it again till a value is found and
             use the following tags as appropriate separated by commas : {IEM_TAGS}
             """
        )

    @property
    def api_key(self):
        return self._api_key

    @api_key.setter
    def api_key(self, api_key):
        logger.info("Validating API Key.")
        self._client = genai.Client(api_key=api_key)
        try:
            _ = self._client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents="Hello"
            )
            self._api_key = api_key
        except errors.APIError as e:
            if e.code in [401, 403]:
                self.detail_queue.put(None)
                logger.error("Given API Key is Invalid")
                logger.critical("Stoping this Thread.")
                raise ValueError
            elif e.code in [429]:
                # Rate limited — key is valid but throttled, retry with backoff
                logger.debug("Key Is Valid but Rate Limited. Trying Again")
                time.sleep(min(2 ** self.try_cnt, 60))
                if self.try_cnt == self.MAX_TRIES:
                    self.detail_queue.put(None)
                    logger.error("API Key is rate limited (429), even after multiple retries.")
                    logger.critical("Stoping this Thread.")
                    raise ValueError
                self.try_cnt += 1
                self.api_key = api_key
            elif e.code in [500, 503, 504]:
                logger.debug(f"Google is Sending {e.code}. Trying Again.")
                time.sleep(min( 2 ** self.try_cnt, 60))
                if self.try_cnt == self.MAX_TRIES:
                    self.detail_queue.put(None)
                    logger.warning(f"Google Is Sending 5XX code, Even after Multiple Retries.")
                    logger.critical("Stoping This Thread.")
                    raise ValueError
                self.try_cnt += 1
                self.api_key = api_key
            else:
                # Unexpected error code — don't silently accept the key
                self.detail_queue.put(None)
                logger.exception("Unhandled Exception Thrown From API")
                logger.critical("Stoping This Thread")
                raise ValueError

    def live_detail_fetcher(self):
        while True:
            task = self.job_queue.get()
            if task is None:
                logger.info("Thread has completed it's work.")
                logger.info("Thread is Stopping.")
                self.detail_queue.put(None)
                return
            job, job_no = task
            job_query = f"Find Details about this IEM as per the system instruction using search grounding : '{list(job.keys())}'"
            logger.info(f"SENDING | Job {job_no} : {list(job.keys())}")
            response = self.api_multi_try("gemma-4-31b-it", job_query, self._detail_fetcher_config)
            if response is None:
                logger.error(f"INVALID RESPONSE | Job {job_no} : {list(job.keys())}")
                continue
            json_query = f"Take this Information : '{response.text}' and parse it to proper JSON as Per the Given Schema"
            logger.info(f"PARSING | Job {job_no} : {list(job.keys())}")
            json_detail = self.api_multi_try("gemini-3.1-flash-lite", json_query, self._json_parser_config)
            if json_detail is None:
                logger.error(f"PARSING FAILED | Job {job_no} : {list(job.keys())}")
                continue
            detail = json_detail.parsed
            if not detail:
                logger.error(f"LOCAL PARSING FAILED | Job {job_no} : {list(job.keys())}")
                continue
            self.detail_queue.put((job_no, job, detail['results']))

    def api_multi_try(self, model, query, config):
        try_count = 0
        fail_count = 0
        while try_count < self.MAX_TRIES:
            try:
                response = self._client.models.generate_content(
                    model=model,
                    contents=query,
                    config=config
                )
                time.sleep(2)
                return response
            except errors.APIError as e:
                if e.code in [429]:
                    logger.debug("Rate Limited. Trying Again")
                else:
                    logger.debug(f"API Error : {e.code}")
                    fail_count += 1
            except httpx.HTTPError:
                logger.exception("No Internet Connection Found.")
                fail_count += 1
            except Exception:
                logger.exception("Unhandled Error.")
                fail_count += 1
            if fail_count >= self.FAIL_THRESHOLD:
                logger.error(f"Query Failed : {query}")
                return None
            time.sleep(min(2 ** try_count, 60))
            try_count += 1
        logger.error("Exhausted all Retries Without a Proper Response.")
        return None

class CsvScrapper:
    def __init__(self, dire):
        self.dire = dire

    def __str__(self):
        return self.dire

    @property
    def dire(self):
        return self._dire

    @dire.setter
    def dire(self, dire):
        if Path(dire).is_dir():
            self._dire = dire
        else:
            raise ValueError

    def scrap(self):
        csv_data = []
        fails = []
        loaded = 0
        for file in Path(self.dire).rglob("*.csv"):
            try:
                logger.debug(f"READ CSV : {file}")
                data = self.csv_unpacker(file)
                csv_data.append((" ".join(file.stem.split()), data))
                loaded += 1
            except (FileNotFoundError, PermissionError, ValueError):
                fails.append(file)
        data = {"dataSet" : csv_data,
                "fails" : fails,
                "loaded" : loaded}
        return data

    def csv_unpacker(self, file):
        with open(file,"r") as f:
            reader = csv.reader(f)
            next(reader)
            header = []
            data = []
            for line in reader:
                header.append(line[0])
                data.append(line[1])
            return tuple(header), tuple(data)