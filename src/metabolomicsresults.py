import streamlit as st
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import Draw

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from itertools import cycle

from src.common.common import show_fig, load_parquet


def add_color_column(df):
    color_cycle = cycle(px.colors.qualitative.Plotly)
    df["color"] = [next(color_cycle) for _ in range(len(df))]
    return df


@st.dialog("🔎 Filter Feature Matrix")
def filter_dialog(df):
    len_unfiltered = len(df)
    mz = st.slider(
        "*m/z* range",
        df["mz"].min(),
        df["mz"].max(),
        value=(df["mz"].min(), df["mz"].max()),
    )
    rt = st.slider(
        "RT range",
        df["RT"].min(),
        df["RT"].max(),
        value=(df["RT"].min(), df["RT"].max()),
    )
    filter_sirius = st.toggle("keep only metabolites with SIRIUS annotation", False)
    charge = st.selectbox(
        "charge state", ["all"] + sorted(df["charge"].unique().tolist())
    )
    adduct = "all"
    if "adduct" in df.columns:
        adduct = st.selectbox(
            "adduct", ["all"] + sorted(df["adduct"].unique().tolist())
        )
    # filter text
    filter_text = ""
    if rt[0] > df["RT"].min():
        filter_text += f" **RT** min = {rt[0]};"
    if rt[1] < df["RT"].max():
        filter_text += f" **RT** max = {rt[1]};"
    if mz[0] > df["mz"].min():
        filter_text += f" ***m/z*** min = {mz[0]};"
    if mz[1] < df["mz"].max():
        filter_text += f" ***m/z*** max = {mz[1]};"
    if filter_sirius:
        filter_text += " **SIRIUS** annotations only;"
        df_sirius = df[
            [c for c in df.columns if c.startswith("CSI:FingerID_")]
        ].dropna()
        df = df.loc[df_sirius.index, :]
    if charge != "all":
        filter_text += f" **charge** = {charge};"
        df = df[df["charge"] == int(charge)]
    if adduct != "all":
        filter_text += f" **adduct** = {adduct};"
        df = df[df["adduct"] == adduct]
    df = df[(df["mz"] >= mz[0]) & (df["mz"] <= mz[1])]
    df = df[(df["RT"] >= rt[0]) & (df["RT"] <= rt[1])]
    if df.empty:
        st.warning(
            "⚠️ Feature Matrix is empty after filtering. Filter will not be applied."
        )
    _, _, c1, c2 = st.columns(4)
    if c1.button("Cancel", use_container_width=True):
        st.rerun()

    if c2.button("Apply", type="primary", use_container_width=True):
        if len(df) != len_unfiltered and not df.empty:
            st.session_state["feature-matrix-filtered"] = df
            st.session_state["fm-filter-info"] = filter_text.rstrip(";")
        st.rerun()


def metabolite_selection():
    st.session_state.results_metabolite = "none"

    df = load_parquet(
        Path(st.session_state.results_dir, "consensus-dfs", "feature-matrix.parquet")
    )

    if df.empty:
        st.error("FeatureMatrix is empty.")
        return None

    df.set_index("metabolite", inplace=True)
    sample_cols = sorted([col for col in df.columns if col.endswith(".mzML")])
    # Insert a column with normalized intensity values to display as barchart column in dataframe
    df.insert(
        1,
        "intensity",
        df.apply(lambda row: [int(row[col]) for col in sample_cols], axis=1),
    )
    df["intensity"] = df["intensity"].apply(
        lambda intensities: [i / max(intensities) for i in intensities]
    )
    c1, c2, c3 = st.columns([0.5, 0.25, 0.25])
    c1.markdown(f"**Feature Matrix** containing {df.shape[0]} metabolites")
    if "feature-matrix-filtered" in st.session_state:
        if c2.button("❌ Reset", use_container_width=True):
            del st.session_state["feature-matrix-filtered"]
            st.rerun()
        st.success(st.session_state["fm-filter-info"])
    if c3.button("🔎 Filter", use_container_width=True):
        filter_dialog(df)
    if "feature-matrix-filtered" in st.session_state:
        if not st.session_state["feature-matrix-filtered"].empty:
            df = st.session_state["feature-matrix-filtered"]

    event = st.dataframe(
        df,
        column_order=["intensity", "RT", "mz", "charge", "adduct"],
        hide_index=False,
        column_config={
            "intensity": st.column_config.BarChartColumn(
                width="small",
                help=", ".join(
                    [
                        str(Path(col).stem)
                        for col in sorted(df.columns)
                        if col.endswith(".mzML")
                    ]
                ),
            ),
        },
        height=300,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
    )
    rows = event.selection.rows
    if rows:
        return df.iloc[rows[0], :]
    st.info("💡 Select a row (metabolite) in the feature matrix for more information.")
    return None

def metabolite_metrics(metabolite):
    cols = st.columns(5)
    with cols[0]:
        st.metric("*m/z* (monoisotopic)", round(metabolite["mz"], 1))
    with cols[1]:
        st.metric("RT (seconds)", round(metabolite["RT"], 1))
    with cols[2]:
        st.metric("charge", metabolite["charge"])
    with cols[3]:
        st.metric("re-quantified", metabolite["re-quantified"])
    with cols[4]:
        if "adduct" in metabolite:
            st.metric("adduct", metabolite["adduct"])

@st.cache_data
def get_chroms_for_each_sample(metabolite):
    # Get index of row in df where "metabolite" is equal to metabolite
    all_samples = [
        i.replace(".mzML", "") for i in metabolite.index if i.endswith("mzML")
    ]
    dfs = []
    samples = []
    for sample in all_samples:
        # Get feature ID for sample
        fid = metabolite[sample + ".mzML_IDs"]
        path = Path(
            st.session_state.results_dir,
            "ffmid-df" if metabolite["re-quantified"] else "ffm-df",
            sample + ".parquet",
        )
        f_df = load_parquet(path)
        if fid in f_df.index:
            dfs.append(f_df.loc[[fid]])
            samples.append(sample)
    df = pd.concat(dfs)
    df["sample"] = samples
    df = add_color_column(df)
    return df


@st.cache_resource
def get_feature_chromatogram_plot(df):
    # Create an empty figure
    fig = go.Figure()
    # Loop through each row in the DataFrame and add a line trace for each
    for _, row in df.iterrows():
        fig.add_trace(
            go.Scatter(
                x=row["chrom_RT"],  # Assuming chrom_RT is a list of values
                y=row[
                    "chrom_intensity"
                ],  # Assuming chrom_intensity is a list of values
                mode="lines",  # Line plot
                name=row["sample"],  # Giving each line a name based on its index
                marker=dict(color=row["color"]),
            )
        )
    # Update layout of the figure
    fig.update_layout(
        xaxis_title="retention time (s)",
        yaxis_title="intensity (counts)",
        plot_bgcolor="rgb(255,255,255)",
        template="plotly_white",
        showlegend=True,
        margin=dict(l=0, r=0, t=0, b=0),
        height=300,
    )
    return fig


@st.cache_resource
def get_feature_intensity_plot(metabolite):
    df = pd.DataFrame(
        {
            "sample": [i for i in metabolite.index if i.endswith(".mzML")],
            "intensity": metabolite["intensity"],
        }
    )
    df = add_color_column(df)

    # Create a mapping from sample to color
    color_map = dict(zip(df["sample"], df["color"]))

    # Plot bar chart
    fig = px.bar(
        df, x="sample", y="intensity", color="sample", color_discrete_map=color_map
    )

    fig.update_layout(
        xaxis_title="",
        yaxis_title="intensity (AUC)",
        plot_bgcolor="rgb(255,255,255)",
        template="plotly_white",
        showlegend=True,
        margin=dict(l=0, r=0, t=0, b=0),
        height=300,
    )
    return fig


def sirius_summary(s):
    """s containing SIRIUS, CSI:FingerID and CANOPUS results for selected metabolite"""
    samples = list(set(s.split("_")[1] for s in s.index if s.startswith("SIRIUS_")))
    c1, c2 = st.columns(2)
    if not samples:
        return
    if len(samples) > 1:
        sample = c1.selectbox("select file", samples)
    else:
        sample = samples[0]

    s = s[[i for i in s.index if f"_{sample}_" in i]]
    new_index = [
        "formula (CSI:FingerID)",
        "name",
        "InChI",
        "smiles",
        "formula (SIRIUS)",
        "pathway",
        "superclass",
        "class",
        "most specific class",
    ]
    s.index = new_index
    custom_order = [
        "name",
        "formula (SIRIUS)",
        "formula (CSI:FingerID)",
        "InChI",
        "smiles",
        "pathway",
        "superclass",
        "class",
        "most specific class",
    ]
    s = s.reindex(custom_order)
    s.name = f"{sample}; {s.name}"
    s = s.dropna()
    with c1:
        s.index = [i.replace(f"_{sample}_", " ") for i in s.index]
        st.dataframe(s, use_container_width=True)
    with c2:
        if "InChI" in s.index:
            molecule = Chem.MolFromInchi(s["InChI"])
            img = Draw.MolToImage(molecule)
            st.image(img, use_container_width=True)