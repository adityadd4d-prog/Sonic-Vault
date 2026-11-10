"""
This Program Is Responsible For Creating The SQLite3 Database Used By 'frontend.py' Program.
This Creates The Database By Scraping The Measurement Data From The Given Directory Then Using
LLMs To Get Their Specification Details Using Search Grounding And Then Converting That Information To
A Structured JSON Response. All This Information Is Then Stored In The Created SQLite3 Database.
"""

import sqlite3
from pathlib import Path
import threading
import queue
import logging
from sys import exit
from contextlib import closing
from datetime import datetime

import score
import Scrapper
from Scrapper import IEM_TAGS
from constants import COLUMNS, BAND_COLUMNS

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def main():
    dire = input("Directory Path : ").strip()

    setup_loggers()

    logger.info("Reading CSV ...")
    try:
        reader = Scrapper.CsvScrapper(dire)
    except ValueError:
        logger.critical("Given Directory is Invalid!")
        exit()

    data = reader.scrap()
    logger.info(f"Finished Reading. Loaded {data['loaded']} CSV Files. Failed To Load {len(data['fails'])} Files.")

    if data["loaded"] <= 20:
        logger.critical("The Directory Contains Very Few Files (Less Than 20).")
        logger.critical("Terminating Program...")
        exit()


    if data["fails"]:
        logger.error(f"The Failed Files Were : {data['fails']}")
    opt = input("\nWould You Like to Proceed With Database Creation [y/N] : ").strip()
    if opt.lower() not in ["y", "yes"]:
        logger.info("Database Creation Cancelled.")
        logger.info("Exiting Program...")
        exit()

    db_name = "Audio.db"
    check(db_name)
    api_keys = get_api_keys()

    job_queue = queue.Queue()
    response_queue = queue.Queue()

    # Spawning All Threads
    threads_trackers = start_job_consumer_threads(api_keys, job_queue, response_queue)
    sqlite_thread = threading.Thread(target=sqlite3_thread, args=(db_name, data, job_queue, response_queue, len(threads_trackers)), name="Database Writer")
    sqlite_thread.start()

    # Waiting For All Thread To Finish Their Work
    for thread in threads_trackers:
        thread.join()
    sqlite_thread.join()

    logger.info("Database Creation Finished.")
    logger.info("Exiting Program...")


def setup_loggers():
    """
    Sets Up The Loggers For Use In The Pipeline.
    """
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


def get_api_keys():
    """
    :return: A Tuple Containing All The API Keys Found In The File.
    """
    while True:
        try:
            file_name = input("\nEnter File Name In Which API Keys Are Stored : ").strip()
            logger.info(f"Reading {file_name} ...")
            api_keys = []
            with open(file_name, "r") as file:
                for line in file:
                    api_keys.append(line.strip())
                return tuple(api_keys)
        except FileNotFoundError:
            logger.error(f"{file_name} Not Found !")
        except PermissionError:
            logger.error("You Do Not Have Permission To Read This File !")
        ch = input("Would Like To Try With Another File [Y/n] : ").strip()
        if ch.lower() in ["n", "no"]:
            logger.warning("No API Keys To Spawn Threads !")
            logger.info("Exiting Program...")
            exit()


def sqlite3_thread(db_name, data, job_queue, response_queue, thread_count):
    """
    This Is The Writer Thread Responsible For Handling All The Writes To The Database.
    It Takes Details From The Response Queue And Writes Them To The Database.
    """
    with sqlite3.connect(db_name) as connection:
        cursor = connection.cursor()

        db_schema(cursor) # Sets The Schema Of The Database
        connection.commit()
        logger.info("Database Schema Successfully Commited.")

        fill_tags_table(cursor) # Fills The Tags Table
        insert_data(cursor, data, job_queue, thread_count) # Fills The Main, Scores And Measurement Table And Queues All The Jobs
        logger.info("CSV Data Successfully Inserted.")
        connection.commit()

        # Generates A Lookup Dict Of Tags To Reduce Query Time
        tags = { tag : tag_id for tag_id, tag in cursor.execute("SELECT * FROM tags").fetchall()}

        pill_count = 0
        while True:

            # Exit Conditions For The Loop
            if thread_count == 0:
                logger.critical("Failed To Start Any Threads!")
                break
            if pill_count == thread_count:
                break

            response = response_queue.get()
            if response is None:
                pill_count += 1
                continue

            job_no, job, job_details = response

            query = "INSERT INTO details (main_id, brand, name, driver, device_type, is_wireless, link, anc, freq_range, impedance, connector_type, signature, mrp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            logger.info(f"WRITING | Job {job_no} : {list(job.keys())}")

            for iem in job_details:

                # Gets main_id For Use In Queries
                try:
                    idx = job[iem['search_name'].lower()]
                except KeyError:
                    logger.exception(f"Key : {iem['search_name']} Not Found in {job.keys()}")
                    logger.error(f"Skipping Details For This IEM : {iem['brand']} {iem['name']}")
                    continue

                # Writes All Tags Relations
                try:
                    cursor.executemany("INSERT OR IGNORE INTO tag_relations (main_id, tag_id) VALUES (?, ?)",[(idx, tags[tag.strip()]) for tag in iem['tags'].split(",")] )
                except (sqlite3.DatabaseError, KeyError):
                    logger.exception(f"Failed To Insert Tags | Job {job_no} : {iem['tags']} Not Found In {tags}")

                # Writes All Specification Details
                values = (idx, iem['brand'], iem['name'], iem['driver'], iem['device_type'], iem['is_wireless'], iem['link'], iem['anc'], iem['freq_range'], iem['impedance'], iem['connector_type'], iem['signature'], iem['mrp'])
                try:
                    cursor.execute(query, values)
                except sqlite3.DatabaseError:
                    logger.exception(f"Failed To Insert Details | Job {job_no} : {values}")
            connection.commit()
        logger.info("All Data Written")
        logger.info("Stopping SQLite Writer Thread")


def start_job_consumer_threads(api_keys, job_queue, response_queue):
    """
    This Function Spawns A Data Fetcher Worker Thread On Per API Key
    :param api_keys: A List Of All Available API Keys
    :return: A List Of Object To Access Each thread
    """
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
    """
    It Writes All The Data Scraped From The CSV Files, Scores Them And Inserts Them In The Database.
    It Also Batches The Names Of the IEMs In 5 And Inserts Them Into The Job Queue.
    It Also Inserts The Poison Pills According To The Number Of Threads Spawned.
    """

    freqs = ", ".join(COLUMNS)
    marks = ", ".join("?" * len(COLUMNS))
    bands = ", ".join(BAND_COLUMNS)
    band_marks = ", ".join("?" * len(BAND_COLUMNS))
    measurements_query = f"INSERT OR IGNORE INTO measurements (main_id, {freqs}) VALUES (?, {marks})"
    main_query = "INSERT INTO main (name) VALUES (?)"
    score_query = f"INSERT INTO scores (main_id, {bands}) VALUES (?, {band_marks})"

    job = {}
    job_no = 1

    scored_data = score.score_data(data["dataSet"])

    # Writing The Scraped Data and Scores To The Database
    for name, measurements, scores in scored_data:

        try:
            cursor.execute(main_query, (name,))
            main_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            main_id = cursor.execute("SELECT id FROM main WHERE name = ?", (name,)).fetchone()[0]

        detail_id = cursor.execute("SELECT id FROM details WHERE main_id = ?", (main_id,)).fetchone()
        if not detail_id:
            job[name.lower()] = main_id

        cursor.execute(measurements_query, (main_id, *measurements))

        if scores is not None:
            cursor.execute(score_query, (main_id, *scores))

        # Batching Together IEM Names Into 5
        if len(job) == 5: # Change The Number Here To Increase/Decrease The Batch Volume
            job_queue.put((job, job_no))
            logger.debug(f"Job {job_no} Queued : {list(job.keys())}")
            job_no += 1
            job = {}
    if job:
        job_queue.put((job, job_no))
        logger.debug(f"Job {job_no} Queued : {list(job.keys())}")

    # Putting Poison Pills
    for _ in range(thread_count):
        job_queue.put(None)


def db_schema(cursor):
    # Schema For The SQLite3 Database

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
                    device_type TEXT,
                    is_wireless TEXT,
                    link TEXT,
                    anc TEXT,   
                    freq_range TEXT,
                    impedance TEXT,
                    connector_type TEXT,
                    signature TEXT,
                    mrp REAL,
                    FOREIGN KEY (main_id) REFERENCES main(id)
                )
              """)

    freq_cols = ",\n".join(f"{c} REAL" for c in COLUMNS)

    # Measurement Table
    cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS measurements ( 
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    main_id INTEGER UNIQUE NOT NULL,
                    {freq_cols} ,
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

    bands = " REAL,".join(BAND_COLUMNS)

    cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    main_id INTEGER UNIQUE,
                    {bands} REAL,
                    FOREIGN KEY (main_id) REFERENCES main(id)
                )
            """)


def fill_tags_table(cursor):
    cursor.executemany("INSERT OR IGNORE INTO tags (tag) VALUES (?)", [(tag,) for tag in IEM_TAGS])


def check(db_name: str) -> None:
    """
    Checks if 'db_name' exists in the current directory.
    If found, prompts the user to back it up and remove the original, or exit.
    """
    current_dir = Path.cwd()
    db_file = current_dir / db_name

    if not db_file.is_file():
        return

    logger.warning(f"There already exists a '{db_name}' file.")
    opt = input("\nWould you like to continue? [y/N]: ").strip().lower()

    if opt in ("yes", "y"):
        backup_folder = current_dir / "backups"
        backup_folder.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_folder / f"{db_file.name}_{timestamp}"
        logger.info(f"Backing up existing database to: {backup_file}")

        # Explicitly close connections so the file lock is released before unlink()
        with closing(sqlite3.connect(db_file)) as source_conn, \
                closing(sqlite3.connect(backup_file)) as backup_conn:
            source_conn.backup(backup_conn)

        db_file.unlink()
        logger.info("Old database file removed.")
    else:
        logger.info("Database creation cancelled. Exiting program...")
        exit(0)


if __name__ == "__main__":
    main()

