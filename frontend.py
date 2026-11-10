"""
A Frontend UI to Query The SQLite Database Created Using The 'project.py' Script.
This UI Offers For Querying The Database Directly Via Using Names And
It Also Offers The Feature of Building Dynamic Queries Using Different Criteria Such As Tags, Brands, Connector Type and Price Range.
It Also Offers Another Section Where One Can Compare Upto 3 Different IEMs By Overlaying Their Frequency Response Graphs Over Each Other
And Arranging Their Specifications In A Tabular Form.
"""

import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

from constants import HARMAN_2019_RAW, FREQUENCY


PAGE_SIZE = 5

def main():
    st.title("Sonic Vault")
    search, iem_compare, similarity_search = st.tabs(["Search", "Compare", "Similarity Search"])

    connection = db_connection()
    lookup_dict, names, brands, tags = load_iem_data(connection)

    with search:
        search_menu(connection, lookup_dict, names, brands, tags)

    with iem_compare:
        compare_menu(connection, lookup_dict, names)

    with similarity_search:
        similarity_search_menu(connection, names, lookup_dict)

def similarity_search_menu(connection, names, lookup_dict):
    st.header("Similarity Search", anchor=False)
    st.text("Perform Similarity Search By")
    col1, col2 = st.columns([0.05, 0.95], vertical_alignment="center")
    with col1:
        st.session_state.switch = st.toggle("", value=False, label_visibility="collapsed")
    with col2:
        if st.session_state.switch:
            st.markdown("**Sound Signature**")
        else:
            st.markdown("**IEM**")
    if st.session_state.switch:
        with st.container(border=True):
            col3, col4, col5 = st.columns(3)
            with col3:
                st.markdown("**BASS**")
                st.session_state.Bass = st.toggle("Advanced Options", value=False, key="t1")
                if st.session_state.Bass:
                    with st.container(border=True):
                        sub_bass = st.slider("Sub Bass", min_value=0, max_value=10)
                        mid_bass = st.slider("Mid Bass", min_value=0, max_value=10)
                        upper_bass = st.slider("Upper Bass", min_value=0, max_value=10)
                else:
                    with st.container(border=True):
                        bass = st.slider("Bass", min_value=0, max_value=10)
            with col4:
                st.text("MIDS")
                st.session_state.Mids = st.toggle("Advanced Options", value=False, key="t2")
                if st.session_state.Mids:
                    with st.container(border=True):
                        lower_mids = st.slider("Lower Mids", min_value=0, max_value=10)
                        center_mids = st.slider("Center Mids", min_value=0, max_value=10)
                        upper_mids = st.slider("Upper Mids", min_value=0, max_value=10)
                else:
                    with st.container(border=True):
                        mids = st.slider("Mids", min_value=0, max_value=10)

            with col5:
                st.text("TREBLE")
                st.session_state.Treble = st.toggle("Advanced Options", value=False, key="t3")
                if st.session_state.Treble:
                    with st.container(border=True):
                        lower_treble = st.slider("Presence", min_value=0, max_value=10)
                        mid_treble = st.slider("Brilliance", min_value=0, max_value=10)
                        upper_treble = st.slider("Air", min_value=0, max_value=10)
                else:
                    with st.container(border=True):
                        treble = st.slider("Treble", min_value=0, max_value=10)

            submitted = st.button("🔍︎ Search", key="b1")

    else:
        col1, col2 = st.columns([0.7, 0.3])
        with col1:
            search_iem = st.selectbox("Select IEM", names, label_visibility="collapsed", index=None)
        with col2:
            search = st.button("🔍︎ Search", key="search_similarity")
        if search and search_iem:
            iem_display(lookup_dict[search_iem], connection)



def compare_menu(connection, lookup_dict, names):
    """
    This Tab Is Responsible For Handling The Comparing Part Of The Program And Helps Compare Upto 3 IEMs.
    """
    st.header("Compare", anchor=False)
    st.text("Select IEMs To Compare : ")
    iems = st.multiselect("Select IEMs To Compare : ", names, label_visibility="collapsed", max_selections=3) # Change max_selection to compare More IEMs
    if len(iems) != 0:
        with st.container(border=True):
            plot_response_graphs(connection,[lookup_dict[iem] for iem in iems])
            labels = ["Brand", "Name", "Drivers", "Device Type", "Wireless Available", "ANC", "Frequency Response", "Impedance",
                  "Connector Type", "Sound Signature", "Maximum Retail Price", "Link"]
            compare_data = {"Specifications" : labels}
            for iem in iems:
                details = query_search(f"SELECT * FROM details WHERE main_id = {lookup_dict[iem]}", connection)
                if details is None:
                    st.warning(f"Details not found for {iem}, skipping.")
                    continue
                measurements = query_search(f"SELECT * FROM measurements WHERE main_id = {lookup_dict[iem]}", connection)
                compare_data[iem] = [*details[2:7], *details[8:13], f"₹ {details[13]}", details[7]]
            compare_df = pd.DataFrame(compare_data)
            st.table(compare_df)


def search_menu(connection, lookup_dicts, names, brands, tags):
    """
    This Tab Is Responsible For Handling The Search Part of The Program and Help Look Through Various IEM Details.
    """
    st.header("Search", anchor=False)
    st.text("Which IEM Are You Looking For ?")

    st.session_state.advanced = st.toggle("Advanced Filters", value=False)
    if st.session_state.advanced:
        with (st.form("Advanced Filters")):
            selected_tags = st.multiselect("Select Tags :", sorted(tags))
            col1, col2 = st.columns(2)
            with col1:
                brand = st.multiselect("Brand : ", brands, max_selections=3)
            with col2:
                c_type = st.multiselect("Connector Type : ", ["0.78mm 2 Pin", "0.75mm 2 Pin", "MMCX", "Fixed Cable", "Wireless"])
            st.text("Price Range :")
            col3, col4 = st.columns(2)
            with col3:
                l_price = st.number_input("From :", min_value=0.0, max_value=2000000.0, value=0.0, step=1.0)
            with col4:
                u_price = st.number_input("To :", min_value=0.0, max_value=2000000.0, value=5000.0, step=1.0)
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
    """
    This Helps Build A Dynamic SQLite Query Based On The Input Parameters Given To The Function
    """
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


def list_iem(iems, connection):
    """
    This Helps Generate Page Display When The Number Of IEMs To Display Exceeds 5.
    It Does So That By Making Sure That At Any Given Time There Are No More Than 5 IEM Details Displayed
    Even If The Query Fetched More Than 5 Results.
    """
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
    # It Help Generates A Display Card For Displaying IEM Details And Frequency Graph
    details = query_search(f"SELECT * FROM details WHERE main_id = {idx}",connection)
    if details is None:
        st.error("IEM Details Not Found!")
        return
    with st.container(border=True):
        if details[7] != "Not Available":
            st.subheader(f"[{details[2] + " " + details[3]}]({details[7]})", anchor=False)
        else:
            st.subheader(f"{details[2] + " " + details[3]}", anchor=False)
        plot_response_graphs(connection, list([idx]))
        labels = ["Brand", "Name", "Drivers", "Device Type", "Wireless Available", "ANC", "Frequency Response", "Impedance",
                  "Connector Type", "Sound Signature", "Maximum Retail Price"]
        values = [*details[2:7], *details[8:13], f"₹ {details[13]}"]
        spec_df = pd.DataFrame({"Specification": labels, "Value": values})
        st.table(spec_df)


def plot_response_graphs(connection, main_ids):
    # Handles The Plotting of Logarithmic Graphs For The Frequency Response Graphs
    target_df = pd.DataFrame({
        "Frequency": FREQUENCY,
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
    # Returns The Frequency Response Data Of The IEM In A Pandas DataFrame
    result = _conn.execute(f"SELECT * FROM measurements WHERE main_id = ?", (main_id,)).fetchone()
    if result is None:
        return None
    return pd.DataFrame({"Frequency" : FREQUENCY, "Values" : result[2:]})


@st.cache_resource
def db_connection():
    # Caching The Connection To Prevent Opening of Different Connections on Each New Query
    try:
        connection = sqlite3.connect("file:Audio.db?mode=ro", uri=True, check_same_thread=False)
        return connection
    except sqlite3.OperationalError:
        st.toast("❌ Database Not Found !")
        st.stop()


@st.cache_data
def load_iem_data(_conn):
    """
    Caching all The Frequently Used Data To Reduce Search Times

    :returns
    A Tuple Containing The Frequently Used Data Such As IEM names, IEM brand names and tags Used
    """
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