import streamlit as st
import sqlite3
import pandas as pd
from reference_data import HARMAN_2019_RAW, HARMAN_2019_FREQUENCY
import plotly.express as px

def main():
    st.title("Sonic Vault")
    search, iem_compare = st.tabs(["Search", "Compare"])

    connection = db_connection()
    lookup_dict, names, brands, tags = load_iem_data(connection)

    with search:
        search_menu(connection, lookup_dict, names, brands, tags)

    with iem_compare:
        compare_menu(connection, lookup_dict, names)

def compare_menu(connection, lookup_dict, names):
    st.header("Compare")
    st.text("Select IEMs To Compare : ")
    iems = st.multiselect("Select IEMs To Compare : ", names, label_visibility="collapsed", max_selections=3)
    if len(iems) != 0:
        with st.container(border=True):
            plot_response_graphs(connection,[lookup_dict[iem] for iem in iems])
            labels = ["Brand", "Name", "Drivers", "ANC", "Frequency Response", "Impedance",
                      "Connector Type", "Sound Signature", "Maximum Retail Price"]
            compare_data = {"Specifications" : labels}
            measurements_data = {}
            for iem in iems:
                details = query_search(f"SELECT * FROM details WHERE main_id = {lookup_dict[iem]}", connection)
                if details is None:
                    st.warning(f"Details not found for {iem}, skipping.")
                    continue
                measurements = query_search(f"SELECT freqs, value FROM measurements WHERE main_id = {lookup_dict[iem]}", connection)
                compare_data[iem] = [*details[2:10] , f"{details[10]} USD"]
                measurements_data[iem] = measurements
            compare_df = pd.DataFrame(compare_data)
            st.table(compare_df)


def search_menu(connection, lookup_dicts, names, brands, tags):
    st.header("Search")
    st.text("Which IEM Are You Looking For ?")
    
    if st.checkbox("Advanced Filter"):
        with (st.form("Advanced Filters")):
            selected_tags = st.multiselect("Select Tags :", sorted(tags))
            col1, col2 = st.columns(2)
            with col1:
                brand = st.multiselect("Brand : ", brands, max_selections=3)
            with col2:
                c_type = st.multiselect("Connector Type : ", ["0.78mm 2Pin", "0.75mm 2 Pin", "MMCX"])
            st.text("Price Range :")
            col3, col4 = st.columns(2)
            with col3:
                l_price = st.number_input("From :", min_value=0.0, max_value=20000.0, value=0.0, step=1.0)
            with col4:
                u_price = st.number_input("To :", min_value=0.0, max_value=20000.0, value=50.0, step=1.0)
            submitted = st.form_submit_button("🔍︎ Search")
        if submitted:
            query = format_query(brand, c_type, l_price, u_price, selected_tags, tags)
            st.session_state.search_results = query_search_all(query, connection)
            st.session_state.page = 0
        if "search_results" in st.session_state and st.session_state.search_results:
            list_iem(st.session_state.search_results, connection)
        elif "search_results" in st.session_state:
            st.info("No IEMs found matching your filters.")
    else:
        col1, col2 = st.columns([0.7, 0.3])
        with col1:
            search_iem = st.selectbox("Which IEM Are You Looking For ?", names, label_visibility="collapsed", index=None)
        with col2:
            search = st.button("🔍︎ Search")
        if search and search_iem:
            iem_display(lookup_dicts[search_iem], connection)


def format_query(brand, c_type, l_price, u_price, selected_tags, lookup_tags):
    temp_query = []

    if brand:
        temp = ", ".join(f"'{name}'" for name in brand)
        temp_query.append(f"brand IN ({temp})")

    if c_type:
        temp = ", ".join(f"'{name}'" for name in c_type)
        temp_query.append(f"connector_type IN ({temp})")

    temp_query.append(f"mrp >= {l_price}")
    temp_query.append(f"mrp <= {u_price}")

    if selected_tags:
        tags_id = ", ".join(f"'{lookup_tags[name]}'" for name in selected_tags)
        temp = f"""
                SELECT main_id FROM tag_relations WHERE tag_id IN ({tags_id}) GROUP BY main_id HAVING COUNT(DISTINCT tag_id) = {len(selected_tags)}
                """
        temp_query.append(f"main_id IN ({temp})")

    query = "SELECT main_id FROM details WHERE " + " AND ".join(temp_query)
    return query

PAGE_SIZE = 5

def list_iem(iems, connection):
    page = st.session_state.get("page", 0)
    total_pages = max(1, -(-len(iems) // PAGE_SIZE))
    page = min(page, total_pages - 1)

    start = page * PAGE_SIZE
    end = start + PAGE_SIZE

    for iem in iems[start:end]:
        iem_display(*iem, connection)

    if total_pages > 1:
        col1, col2, _ = st.columns([1, 1, 8])
        with col1:
            if st.button("<", disabled=(page == 0)):
                st.session_state.page = page - 1
                st.rerun()
        with col2:
            if st.button(">", disabled=(page >= total_pages - 1)):
                st.session_state.page = page + 1
                st.rerun()

def iem_display(idx, connection):
    details = query_search(f"SELECT * FROM details WHERE main_id = {idx}",connection)
    if details is None:
        st.error("IEM Details Not Found!")
        return
    with st.container(border=True):
        st.subheader(f"{details[2]} {details[3]}")
        labels = ["Brand", "Name", "Drivers", "ANC", "Frequency Response", "Impedance",
                  "Connector Type", "Sound Signature", "Maximum Retail Price"]
        values = [*details[2:10] , f"{details[10]} USD"]
        spec_df = pd.DataFrame({"Specification": labels, "Value": values})
        st.table(spec_df)
        plot_response_graphs(connection, list([idx]))


def plot_response_graphs(connection, main_ids):
    target_df = pd.DataFrame({
        "Frequency": HARMAN_2019_FREQUENCY,
        "Values": HARMAN_2019_RAW,
        "curve": "Harman Target 2019",
    })
    plot_data = [target_df]
    for main_id in main_ids:
        df = load_measurement(connection, main_id)
        if df is None:
            continue
        temp = query_search(f"SELECT name FROM main WHERE id = {main_id}", connection)
        df["curve"] = temp[0]
        plot_data.append(df)

    final_data = pd.concat(plot_data, ignore_index=True)
    fig = px.line(
        final_data,
        x="Frequency",
        y="Values",
        color="curve",
        log_x=True,
        labels={"Frequency": "Frequency (Hz)", "Values": "Level (dB)"},
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    max_abs = final_data["Values"].abs().max()
    fig.update_yaxes(range=[-max_abs, max_abs])
    st.plotly_chart(fig, use_container_width=True)

@st.cache_data
def load_measurement(_conn, main_id):
    result = _conn.execute(f"SELECT freqs, value FROM measurements WHERE main_id = ?", (main_id,)).fetchone()
    if result is None:
        return None
    freq, value = result
    freqs = [float(f) for f in freq.split(",")]
    values = [float(v) for v in value.split(",")]
    return pd.DataFrame({"Frequency" : freqs, "Values" : values})

@st.cache_resource
def db_connection():
    try:
        connection = sqlite3.connect("file:Audio.db?mode=ro", uri=True, check_same_thread=False)
        return connection
    except sqlite3.OperationalError:
        st.toast("❌ Database Not Found !")
        st.stop()

@st.cache_data
def load_iem_data(_conn):
    cursor = _conn.cursor()
    data = cursor.execute("SELECT * FROM main").fetchall()
    lookup_dict = {name : main_id for main_id, name in data}
    names = sorted([name for name in lookup_dict.keys()])
    brands = sorted([brand[0] for brand in cursor.execute("SELECT DISTINCT brand FROM details").fetchall()])
    tags_data = cursor.execute("SELECT * FROM tags").fetchall()
    tags = {tag: tag_id for tag_id, tag in tags_data}
    return lookup_dict, names, brands, tags

@st.cache_data
def query_search(query, _conn):
    cursor = _conn.cursor()
    return cursor.execute(query).fetchone()

@st.cache_data
def query_search_all(query, _conn):
    cursor = _conn.cursor()
    return cursor.execute(query).fetchall()

if __name__ == "__main__":
    main()