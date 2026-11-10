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

    scores_df = load_all_scores(connection)

    if st.session_state.switch:
        with st.container(border=True):
            col3, col4, col5 = st.columns(3)
            with col3:
                st.markdown("**BASS**")
                st.session_state.Bass = st.toggle("Advanced Options", value=False, key="t1")
                if st.session_state.Bass:
                    with st.container(border=True):
                        sub_bass = st.slider("Sub Bass", min_value=1.0, max_value=10.0, value=5.5, step=0.1)
                        mid_bass = st.slider("Mid Bass", min_value=1.0, max_value=10.0, value=5.5, step=0.1)
                        upper_bass = st.slider("Upper Bass", min_value=1.0, max_value=10.0, value=5.5, step=0.1)
                else:
                    with st.container(border=True):
                        bass = st.slider("Bass", min_value=1.0, max_value=10.0, value=5.5, step=0.1)
            with col4:
                st.markdown("**MIDS**")
                st.session_state.Mids = st.toggle("Advanced Options", value=False, key="t2")
                if st.session_state.Mids:
                    with st.container(border=True):
                        lower_mids = st.slider("Lower Mids", min_value=1.0, max_value=10.0, value=5.5, step=0.1)
                        center_mids = st.slider("Center Mids", min_value=1.0, max_value=10.0, value=5.5, step=0.1)
                        upper_mids = st.slider("Upper Mids", min_value=1.0, max_value=10.0, value=5.5, step=0.1)
                else:
                    with st.container(border=True):
                        mids = st.slider("Mids", min_value=1.0, max_value=10.0, value=5.5, step=0.1)

            with col5:
                st.markdown("**TREBLE**")
                st.session_state.Treble = st.toggle("Advanced Options", value=False, key="t3")
                if st.session_state.Treble:
                    with st.container(border=True):
                        lower_treble = st.slider("Presence", min_value=1.0, max_value=10.0, value=5.5, step=0.1)
                        mid_treble = st.slider("Brilliance", min_value=1.0, max_value=10.0, value=5.5, step=0.1)
                        upper_treble = st.slider("Air", min_value=1.0, max_value=10.0, value=5.5, step=0.1)
                else:
                    with st.container(border=True):
                        treble = st.slider("Treble", min_value=1.0, max_value=10.0, value=5.5, step=0.1)

            submitted = st.button("🔍︎ Search", key="b1")

        if submitted:
            # 1. Build a target dictionary based on active sliders
            target_scores = {}
            if st.session_state.Bass:
                target_scores.update({"sub_bass": sub_bass, "mid_bass": mid_bass, "upper_bass": upper_bass})
            else:
                target_scores.update({"bass": bass})

            if st.session_state.Mids:
                target_scores.update({"lower_mids": lower_mids, "center_mids": center_mids, "upper_mids": upper_mids})
            else:
                target_scores.update({"mids": mids})

            if st.session_state.Treble:
                target_scores.update(
                    {"lower_treble": lower_treble, "mid_treble": mid_treble, "upper_treble": upper_treble})
            else:
                target_scores.update({"treble": treble})

            # 2. Calculate Euclidean distance for the selected bands
            distance_series = pd.Series(0.0, index=scores_df.index)
            for band, target_val in target_scores.items():
                distance_series += (scores_df[band] - target_val) ** 2

            scores_df["distance"] = distance_series ** 0.5

            # 3. Sort, extract IDs, and pass to pagination
            closest_matches = scores_df.sort_values("distance").head(15)
            results = [(idx,) for idx in closest_matches["main_id"]]

            st.session_state.sim_sig_results = [(idx,) for idx in closest_matches["main_id"]]
            st.session_state.sim_sig_page = 0

        if "sim_sig_results" in st.session_state:
            st.subheader("Closest Matches:")
            list_iem(st.session_state.sim_sig_results, connection, "sim_sig")

    else:
        col1, col2 = st.columns([0.7, 0.3])
        with col1:
            search_iem = st.selectbox("Select IEM", names, label_visibility="collapsed", index=None)
        with col2:
            search = st.button("🔍︎ Find Similar", key="search_similarity")

        if search and search_iem:
            target_id = lookup_dict[search_iem]
            detailed_bands = [
                "sub_bass", "mid_bass", "upper_bass",
                "lower_mids", "center_mids", "upper_mids",
                "lower_treble", "mid_treble", "upper_treble"
            ]
            row = scores_df[scores_df["main_id"] == target_id]
            if row.empty:
                st.warning("No score data available for this IEM.")
            else:
                target_vector = row[detailed_bands].iloc[0]
                scores_df["distance"] = ((scores_df[detailed_bands] - target_vector) ** 2).sum(axis=1) ** 0.5
                closest = scores_df[scores_df["main_id"] != target_id].sort_values("distance").head(15)
                st.session_state.sim_iem_results = [(idx,) for idx in closest["main_id"]]
                st.session_state.sim_iem_page = 0

        if "sim_iem_results" in st.session_state:
            st.subheader("Similar IEMs:")
            list_iem(st.session_state.sim_iem_results, connection, "sim_iem")


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
                  "Connector Type", "Sound Signature", "Maximum Retail Price"]
            compare_data = {"Specifications" : labels}
            for iem in iems:
                details = query_search("SELECT * FROM details WHERE main_id = ?", (lookup_dict[iem],), connection)
                if details is None:
                    st.warning(f"Details not found for {iem}, skipping.")
                    continue
                compare_data[iem] = [*details[2:7], *details[8:13], f"₹ {details[13]}"]
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
            query, params = format_query(brand, c_type, l_price, u_price, selected_tags, tags)
            st.session_state.search_results = query_search_all(query, params, connection)
            st.session_state.search_page = 0

        if "search_results" in st.session_state and st.session_state.search_results:
            list_iem(st.session_state.search_results, connection, "search")
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
    """Builds a parameterized query. Returns (query, params)."""
    clauses, params = [], []

    if brand:
        clauses.append(f"brand IN ({','.join('?' * len(brand))})")
        params.extend(brand)
    if c_type:
        clauses.append(f"connector_type IN ({','.join('?' * len(c_type))})")
        params.extend(c_type)

    clauses.append("mrp >= ?")
    clauses.append("mrp <= ?")
    params.extend([l_price, u_price])

    if selected_tags:
        tag_ids = [lookup_tags[name] for name in selected_tags]
        clauses.append(
            f"main_id IN (SELECT main_id FROM tag_relations "
            f"WHERE tag_id IN ({','.join('?' * len(tag_ids))}) "
            f"GROUP BY main_id HAVING COUNT(DISTINCT tag_id) = ?)"
        )
        params.extend(tag_ids)
        params.append(len(tag_ids))

    return "SELECT main_id FROM details WHERE " + " AND ".join(clauses), tuple(params)


def list_iem(iems, connection, prefix):
    page_key = f"{prefix}_page"
    page = st.session_state.get(page_key, 0)
    total_pages = max(1, -(-len(iems) // PAGE_SIZE))
    page = min(page, total_pages - 1)

    start = page * PAGE_SIZE
    for iem in iems[start:start + PAGE_SIZE]:
        iem_display(*iem, connection)

    if total_pages > 1:
        col1, col2, _ = st.columns([1, 1, 8])
        with col1:
            if st.button("<", key=f"{prefix}_prev", disabled=(page == 0)):
                st.session_state[page_key] = page - 1
                st.rerun()
        with col2:
            if st.button(">", key=f"{prefix}_next", disabled=(page >= total_pages - 1)):
                st.session_state[page_key] = page + 1
                st.rerun()


def iem_display(idx, connection):
    # It Help Generates A Display Card For Displaying IEM Details And Frequency Graph
    details = query_search("SELECT * FROM details WHERE main_id = ?", (idx,), connection)
    if details is None:
        st.caption("Details unavailable for this IEM.")
        return
    with st.container(border=True):
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
        temp = query_search("SELECT name FROM main WHERE id = ?", (main_id,), connection)
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
    data = cursor.execute("SELECT m.id, m.name FROM main m JOIN details d ON d.main_id = m.id").fetchall()
    lookup_dict = {name : main_id for main_id, name in data}
    names = sorted([name for name in lookup_dict.keys()])
    brands = sorted([brand[0] for brand in cursor.execute("SELECT DISTINCT brand FROM details").fetchall()])
    tags_data = cursor.execute("SELECT * FROM tags").fetchall()
    tags = {tag: tag_id for tag_id, tag in tags_data}
    return lookup_dict, names, brands, tags


@st.cache_data
def query_search(query, params, _conn):
    return _conn.execute(query, params).fetchone()


@st.cache_data
def query_search_all(query, params, _conn):
    return _conn.execute(query, params).fetchall()


@st.cache_data
def load_all_scores(_conn):
    return pd.read_sql_query("SELECT s.* FROM scores s JOIN details d ON d.main_id = s.main_id", _conn)


if __name__ == "__main__":
    main()