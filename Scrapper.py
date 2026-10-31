"""
A Module Containing Classes For Scrapper And Data Fetcher Worker Thread
"""

import csv
import logging
import time
from pathlib import Path

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

from reference_data import FREQUENCY

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Valid Tags That Are Accepted By The Program
IEM_TAGS = (
        "Dynamic Driver", "Balanced Armature", "Planar Magnetic", "Electrostatic", "Hybrid", "Tribrid",
        "Neutral", "Warm", "Bright", "Dark", "V Shaped", "U Shaped", "Basshead", "Mid Forward", "Harman Target",
        "Stage Monitor", "Studio Reference", "Casual Listening", "Gaming", "Sports", "Sleep Friendly", "ANC",
        "Detachable Cable", "MMCX", "2 Pin", "Wireless TWS", "Balanced Cable Included", "Tuning Switches",
        "Quadbrid", "Pentabrid", "Hexabrid"
    )


class IemDetails(BaseModel):
    """
    Pydantic Model Describing What Type Of Contents A Model Of IEM Should Have.
    Used To Get Structured Response From The Gemini Model.
    """
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
    """
    The Threads That Are Responsible For Fetching Details Of IEM From Job Queue.
    """
    def __init__(self, api_key, job_queue, detail_queue):
        """
        Intialize The Class Then Just Start The Thread.
        :param api_key: API key from Google Studio AI
        :param job_queue: The Queue From Where The Thread Fetches The Jobs
        :param detail_queue: The Queue Where The Thread Puts Data After Processing It
        """
        self.try_cnt = 0
        self.MAX_TRIES = 15
        self.FAIL_THRESHOLD = 7
        self.job_queue = job_queue
        self.detail_queue = detail_queue
        self.api_key =  api_key
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
                logger.error("Given API Key is Invalid")
                logger.critical("Stoping this Thread.")
                raise ValueError
            elif e.code in [429]:
                logger.debug("Key Is Valid but Rate Limited. Trying Again")
                time.sleep(min(2 ** self.try_cnt, 60))
                if self.try_cnt == self.MAX_TRIES:
                    logger.error("API Key is rate limited (429), even after multiple retries.")
                    logger.critical("Stoping this Thread.")
                    raise ValueError
                self.try_cnt += 1
                self.api_key = api_key
            elif e.code in [500, 503, 504]:
                logger.debug(f"Google is Sending {e.code}. Trying Again.")
                time.sleep(min( 2 ** self.try_cnt, 60))
                if self.try_cnt == self.MAX_TRIES:
                    logger.warning(f"Google Is Sending 5XX code, Even after Multiple Retries.")
                    logger.critical("Stoping This Thread.")
                    raise ValueError
                self.try_cnt += 1
                self.api_key = api_key
            else:
                logger.exception("Unhandled Exception Thrown From API")
                logger.critical("Stoping This Thread")
                raise ValueError

    def live_detail_fetcher(self):
        """
        This Function Is The One That Should Be Run As a Thread. Can Be Run Multiple Times To Run Multiple Instances.
        """
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
        """
        This Handles The Retry Mechanism Of The Class, It Uses Exponential Backoff For The Retry Mechanism.
        :param model: The Model Name That Is To Be Used For Making Calls
        :param query: Query To Be Done
        :param config: The GenerateContentConfig That Is To Be Used To Give Instructions.
        :return: Returns None If It Fails To Get A Valid Response Even After Multiple Retries Else Returns The Response.
        """
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
    """
    This Class Is Responsible For Scraping The Directory For CSV Files And Scrapping The Data In Them.
    """
    def __init__(self, dire):
        """
        :param dire: The Directory On Which The Scrapping Is To Be Performed.
        """
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
        """
        The Main Function That Is Responsible For Scraping The Directory.
        :return: Returns A Dict Containing The Scrapped Data, Failed Files and The No. Of Loaded Files.
        """
        csv_data = []
        fails = []
        loaded = 0
        for file in Path(self.dire).rglob("*.csv"):
            try:
                logger.debug(f"READ CSV : {file}")
                measurements = self.csv_unpacker(file)
                if measurements is None:
                    logger.info(f"{file} Does Not Match Defined Format.")
                    fails.append(file)
                    continue
                csv_data.append((" ".join(file.stem.split()), measurements))
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
                header.append(float(line[0]))
                data.append(float(line[1]))
            if tuple(header) == FREQUENCY:
                return tuple(data)
            else:
                return None
