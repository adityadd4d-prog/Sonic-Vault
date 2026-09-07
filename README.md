# Sonic Vault

#### Video Demo: [Youtube Video](https://youtu.be/XQ1_u9Y5LAo?feature=shared)`

#### Live Site: `[Streamlit](https://sonic-vault.streamlit.app/)`

#### Description:
Sonic Vault is a tool for creating a SQLite database of IEMs
(in-ear monitors). It takes the path of a directory containing CSV files
with IEM frequency response data, fetches details about each IEM using
an LLM, and stores everything in a structured database. A Streamlit
frontend is included for searching and visualising the collected data.
The program uses the `logging` module for easy debugging and job tracking
throughout the whole pipeline.

---

## Demo
The repo comes with an `Audio.db` file containing ~2000 IEM entries. The CSVs
were taken from [AutoEq](https://github.com/jaakkopasanen/AutoEq.git).
You can remove it if you want to build your own : it took ~20 minutes to build
using 30 Gemini API keys (i.e. 30 parallel data fetcher threads).

---

## Prerequisites

- Python 3.x
- Gemini API keys from Google AI Studio
- A directory containing frequency response data in CSV format (2 columns:
  first column containing frequency data in Hz, second column containing
  the reading in dB)

## Installation

```python
pip install -r requirements.txt
```

## Usage

### Build the Database

```python
python project.py
```

- After running, the program prompts for the directory containing the CSV files.
- It then asks for instructions on what to do if a database already exists
  (Replace / Update / Exit).
- After that it asks for Gemini API keys and proceeds to spawn one worker
  thread per key.
- It then spawns the database writer thread and proceeds to insert everything
  into the database.
- While working, it prints logs to the terminal and writes a more detailed
  log file to `Database.log`.

### Launch the Frontend

```python
streamlit run frontend.py
```

There are two tabs in the web UI :-

1. **Search** : used for searching IEMs and filtering them based on criteria
   such as brand, connector type, tags, and price.
2. **Compare** : used for comparing up to 3 IEMs by overlaying their graphs
   and arranging the details in a tabular format.

---

## Project Structure

```
Sonic-Vault/
├── project.py
├── Scrapper.py
├── reference_data.py
├── frontend.py
├── test_project.py
├── Audio.db
└── requirements.txt
```

#### 1. `project.py`
Manages the program entry point and orchestrates database creation. It
reads CSV files, spawns worker threads (one per API key), and coordinates
the job queue and response queue that connect the scraper threads with the
SQLite writer thread.

#### 2. `Scrapper.py`
This module is comprised of :-

1. **IemDetails** : A Pydantic model that defines the structured schema
   for IEM data. It is used alongside `response_mime_type` and
   `response_json_schema` in the `GenerateContentConfig` to enforce
   structured JSON output from Gemini.

2. **DetailFetcherThread** : The class responsible for fetching IEM
   details. It uses Google Search grounding with the `gemma-4-31b-it`
   model to retrieve information from the web, then does a second pass
   with `gemini-3.1-flash-lite` to parse the result into structured JSON.
   A multi-retry mechanism with exponential backoff handles rate limits
   and transient errors.

3. **CsvScrapper** : Handles reading all CSV files in the given
   directory. Each CSV contains two columns (frequency and dB value)
   which are converted into two tuples and inserted into the SQLite
   database.

4. **IEM_TAGS** : A fixed list of valid tags used to classify IEMs.
   Any tag returned by the model that is not in this list is automatically
   discarded, providing a guardrail against LLM hallucinations.

#### 3. `reference_data.py`
Contains the frequency response data from the Harman 2019 In-Ear Target.
This data is used as a reference curve and is overlaid on every frequency
response graph. The file contains two constant tuples :-

1. **HARMAN_2019_FREQUENCY** : Stores the frequency points (in Hz).

2. **HARMAN_2019_RAW** : Stores the corresponding dB values at each
   frequency point.

#### 4. `frontend.py`
A Streamlit-based frontend UI for querying the created database. The UI
is divided into two tabs :-

1. **Search** : Two modes are available. The default mode lets you select
   an IEM by name from a cached dropdown list for fast lookup. The
   Advanced Filter mode lets you filter by brand, connector type, price
   range, and tags; it constructs a SQLite query from those parameters
   and displays paginated results. All queries are cached so repeated
   lookups are fast.

2. **Compare** : Lets you compare the specs and frequency response graphs
   of up to three IEMs side by side. Data is arranged in a table for easy
   comparison.

---

## Design Choices

#### Q. Why Multithreading and Job Batching ?
Ans. Sequential fetching of details is very ineffective and time consuming.
Multithreading allows for parallel operation so multiple jobs can be performed
at once, and batching helps decrease the number of jobs exponentially.

#### Q. Why Two Passes from LLM ?
Ans. Because both search grounding and structured response were not available
on a single model together with a good rate limit on the free plan.

---

## Testing

```python
pytest test_project.py
```

---

## Dependencies

| Library | Purpose |
|---|---|
| `google-genai` | Accessing the LLMs provided by Google for search grounding and JSON parsing |
| `pydantic` | Generating a response model that the LLM uses for structured output |
| `httpx` | Handling errors raised by the `google-genai` underlying implementation |
| `streamlit` | Creating an interactive UI to query the created database |
| `plotly` | Plotting logarithmic graphs to compare IEM frequency response curves |
| `pandas` | Creating DataFrames for plotting frequency response graphs and comparing IEM details |
