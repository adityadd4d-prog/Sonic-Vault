import Scrapper
from Scrapper import IEM_TAGS
import sqlite3
from pathlib import Path
import threading
import queue
import logging
from sys import exit

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def main():
    dire = input("Directory Path : ").strip()
    setup_loggers()
    logger.info("Reading CSV ...")
    reader = Scrapper.CsvScrapper(dire)
    data = reader.scrap()
    logger.info(f"Finished Reading. Loaded {data['loaded']} CSV Files. Failed To Load {len(data['fails'])} Files.")
    if data["fails"]:
        logger.error(f"The Failed Files Were : {data['fails']}")
    opt = input("\nWould You Like to Proceed With Database Creation [y/N] : ").strip()
    if opt.lower() not in ["y", "yes"]:
        logger.info("Database Creation Cancelled.")
        logger.info("Exiting Program...")
        exit()
    db_name = "Audio.db"
    check(db_name)
    api_keys = keys()
    job_queue = queue.Queue()
    response_queue = queue.Queue()
    threads_trackers = start_job_consumer_threads(api_keys, job_queue, response_queue)
    sqlite_thread = threading.Thread(target=sqlite3_thread, args=(db_name, data, job_queue, response_queue, len(threads_trackers)), name="Database Writer")
    sqlite_thread.start()
    for thread in threads_trackers:
        thread.join()
    sqlite_thread.join()
    logger.info("Database Creation Finished.")
    logger.info("Exiting Program...")

def setup_loggers():
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.ERROR)

    screen_handler = logging.StreamHandler()
    screen_handler.setLevel(logging.INFO)
    screen_formater = logging.Formatter(
        "%(asctime)s | %(levelname)-8s : %(message)s",
        datefmt="%H:%M:%S"
    )
    screen_handler.setFormatter(screen_formater)
    root_logger.addHandler(screen_handler)

    file_handler = logging.FileHandler("Scrapper.log", mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formater = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-8s |  %(threadName)-15s | %(funcName)-20s | %(message)s",
        datefmt="%d-%m %H:%M:%S"
    )
    file_handler.setFormatter(file_formater)
    root_logger.addHandler(file_handler)


def keys():
    no_of_keys = int(input("\nHow Many Gemini API Keys do you have : ").strip())
    keys = []
    print(f"\nEnter Keys one by one:-")
    for i in range(1,no_of_keys+1):
        keys.append(input(f"{i}. ").strip())
    return tuple(keys)


def sqlite3_thread(db_name, data, job_queue, response_queue, thread_count):
    with sqlite3.connect(db_name) as connection:
        cursor = connection.cursor()
        db_schema(cursor)
        connection.commit()
        logger.info("Database Schema Successfully Commited.")
        fill_tags_table(cursor)
        insert_data(cursor, data, job_queue, thread_count)
        logger.info("CSV Data Successfully Inserted.")
        connection.commit()
        tags = { tag : tag_id for tag_id, tag in cursor.execute("SELECT * FROM tags").fetchall()}
        pill_count = 0
        while True:
            if thread_count == 0:
                logger.critical("Failed To Start Any Threads!")
                break
            if pill_count == thread_count:
                break
            response = response_queue.get()
            if response is None:
                pill_count += 1
                continue
            job_no, job, details = response
            query = "INSERT INTO details (main_id, brand, name, driver, anc, freq_range, impedance, connector_type, signature, mrp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            logger.info(f"WRITING | Job {job_no} : {list(job.keys())}")
            for iem in details:
                try:
                    idx = job[iem['search_name'].lower()]
                except KeyError:
                    logger.exception(f"Key : {iem['search_name']} Not Found in {job.keys()}")
                    logger.error(f"Skipping Details For This IEM : {iem['brand']} {iem['name']}")
                    continue
                try:
                    cursor.executemany("INSERT OR IGNORE INTO tag_relations (main_id, tag_id) VALUES (?, ?)",[(idx, tags[tag.strip()]) for tag in iem['tags'].split(",")] )
                except (sqlite3.DatabaseError, KeyError):
                    logger.exception(f"Failed To Insert Tags | Job {job_no} : {iem['tags']} Not Found In {tags}")
                values = (idx, iem['brand'], iem['name'], iem['driver'], iem['anc'], iem['freq_range'], iem['impedance'], iem['connector_type'], iem['signature'], iem['mrp'])
                try:
                    cursor.execute(query, values)
                except sqlite3.DatabaseError:
                    logger.exception(f"Failed To Insert Details | Job {job_no} : {values}")
            connection.commit()


def start_job_consumer_threads(api_keys, job_queue, response_queue):
    threads_tracker = []
    for i, key in enumerate(api_keys, start=1):
        try:
            detail_fetcher = Scrapper.DetailFetcherThread(key, job_queue, response_queue)
        except ValueError:
            continue
        thread_name = f"Data Fetcher {i}"
        thread = threading.Thread(target=detail_fetcher.live_detail_fetcher, name=thread_name)
        threads_tracker.append(thread)
        thread.start()
    return threads_tracker


def insert_data(cursor, data, job_queue, thread_count):

    measurements_query = "INSERT OR IGNORE INTO measurements (main_id, freqs, value) VALUES (?, ?, ?)"
    main_query = "INSERT INTO main (name) VALUES (?)"

    job = {}
    job_no = 1
    for item in data["dataSet"]:
        name, measurements = item
        freqs, values = measurements
        freqs_str = ",".join(map(str, freqs))
        values_str = ",".join(map(str, values))

        try:
            cursor.execute(main_query, (name,))
            main_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            main_id = cursor.execute("SELECT id FROM main WHERE name = ?", (name,)).fetchone()[0]

        detail_id = cursor.execute("SELECT id FROM details WHERE main_id = ?", (main_id,)).fetchone()
        if not detail_id:
            job[name.lower()] = main_id

        cursor.execute(measurements_query, (main_id, freqs_str, values_str))

        if len(job) == 5:
            job_queue.put((job, job_no))
            logger.debug(f"Job {job_no} Queued : {list(job.keys())}")
            job_no += 1
            job = {}
    if job:
        job_queue.put((job, job_no))
        logger.debug(f"Job {job_no} Queued : {list(job.keys())}")
    for _ in range(thread_count):
        job_queue.put(None)



def db_schema(cursor):

    # Main Table
    cursor.execute("""
                CREATE TABLE IF NOT EXISTS main (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT COLLATE NOCASE NOT NULL UNIQUE
                )
              """)

    # Details Table
    cursor.execute("""
                CREATE TABLE IF NOT EXISTS details (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    main_id INTEGER UNIQUE NOT NULL,
                    brand TEXT,
                    name TEXT,
                    driver TEXT,
                    anc TEXT,   
                    freq_range TEXT,
                    impedance TEXT,
                    connector_type TEXT,
                    signature TEXT,
                    mrp REAL,
                    FOREIGN KEY (main_id) REFERENCES main(id)
                )
              """)

    # Measurement Table
    cursor.execute("""
                CREATE TABLE IF NOT EXISTS measurements ( 
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    main_id INTEGER UNIQUE NOT NULL,
                    freqs TEXT,
                    value TEXT,
                    FOREIGN KEY (main_id) REFERENCES main(id)
                )
            """)

    # Tags Table
    cursor.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tag TEXT UNIQUE
                )
            """)

    # Tags Relation Table
    cursor.execute("""
                CREATE TABLE IF NOT EXISTS tag_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    main_id INTEGER,
                    tag_id INTEGER,
                    FOREIGN KEY (main_id) REFERENCES main(id),
                    FOREIGN KEY (tag_id) REFERENCES tags(id)
                )
            """)

def fill_tags_table(cursor):
    cursor.executemany("INSERT OR IGNORE INTO tags (tag) VALUES (?)", [(tag,) for tag in IEM_TAGS])


def check(db_name):
    for file in Path(Path.cwd()).iterdir():
        if file.name == db_name:
            logger.warning(f"There Already Exists a '{db_name}' File.")
            opt = input(
                f"\nWould You Like to Replace/Update/Exit it [R/U/E] : ").strip()
            if opt.lower() in ["replace", "r"]:
                Path(db_name).unlink(missing_ok=True)
            elif opt.lower() in ["update", "u"]:
                return
            else:
                logger.info("Database Creation Cancelled.")
                logger.info("Exiting Program...")
                exit()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        exit("Program Terminated!")
