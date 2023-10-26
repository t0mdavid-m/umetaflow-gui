import streamlit as st
from src.common import *
from src.xic import *
from src.masscalculator import get_mass, check_formula

from pathlib import Path
import pandas as pd
import numpy as np

params = page_setup(page="workflow")

st.title("Extracted Ion Chromatograms (EIC/XIC)")

with st.expander("📖 Help"):
    st.markdown(HELP)
 
default_df = pd.DataFrame({"name": [""], "mz": [np.nan], "RT (seconds)": [np.nan], "peak width (seconds)": [np.nan]})

if "workspace" in st.session_state:
    path = Path(st.session_state.workspace, "XIC-input-table.tsv")
    if path.exists():
        # Read dataframe from path (defined in src.eic)
        df = pd.read_csv(path, sep="\t")
    else:
        # Load a default example df
        df = default_df
else:
    # Load a default example df
    df = default_df

with st.expander("**Mass table with metabolites for chromatogram extraction**", True):
    c1, c2 = st.columns(2)
    # Uploader for XIC input table
    c1.file_uploader("Upload XIC input table", type="tsv", label_visibility="collapsed",
                        key="xic-table-uploader", accept_multiple_files=False, on_change=upload_xic_table, args=[df])
    # def update_mass_table()
    edited = st.data_editor(df, use_container_width=True, num_rows="dynamic")
    v_space(1, c2)
    c2.download_button(
        "Download",
        edited.to_csv(sep="\t", index=False).encode("utf-8"),
        "XIC-input-table.tsv",
    )

    c1, c2, c3 = st.columns(3)
    name = c1.text_input(
        "compound name (optional)", "")
    formula = c2.text_input(
        "sum formula", "", help="Enter a neutral sum formula for a new compound in the table.").strip()
    adduct = c3.selectbox(
        "adduct", ["[M+H]+", "[M+Na]+", "[M+2H]2+", "[M-H2O+H]+", "[M-H]-", "[M-2H]2-", "[M-H2O-H]-"], help="Specify the adduct.")

    if c3.button("Add new compound to table", disabled=not formula, help="Calculate mass from formula with given adduct and add to table."):
        if check_formula(formula):
            mz = get_mass(formula, adduct)
            if mz:
                if name:
                    compound_name = f"{name}#{adduct}"
                else:
                    compound_name = f"{formula}#{adduct}"
                new_row = pd.DataFrame({"name": [compound_name], "mz": [mz], "RT": [
                    np.nan], "peak width": [np.nan]})
                edited = pd.concat([edited, new_row], ignore_index=True).to_csv(
                    path, sep="\t", index=False)
                st.rerun()
            else:
                st.warning(
                    "Can not calculate mz of this formula/adduct combination.")
        else:
            st.warning("Invalid formula.")

with st.form("eic_form"):
    st.markdown("**Parameters**")
    st.multiselect("**input mzML files**", [f.stem for f in Path(st.session_state.workspace, "mzML-files").glob("*.mzML")],
                   params["eic_selected_mzML"], key="eic_selected_mzML")

    c1, c2, c3 = st.columns(3)
    c1.radio(
        "time unit for display", ["seconds", "minutes"], index=["seconds", "minutes"].index(params["eic_time_unit"]), key="eic_time_unit", help="Retention time unit for figures and downloadable tables. Rentention time settings have to be specified in seconds."
    )
    c2.number_input("default peak width (seconds)", 1, 600,
                    params["eic_peak_width"], 5, key="eic_peak_width", help="Default value for peak width. Used when a retention time is given without peak width. Adding a peak width in the table will override this setting.")
    c3.number_input(
        "**noise threshold**", 0, 1000000, params["eic_baseline"], 100, key="eic_baseline", help="Peaks below the treshold intensity will not be extracted."
    )
    # Mass tolerance settings
    c1, c2, c3 = st.columns(3)
    c1.radio(
        "mass tolerance unit", ["ppm", "Da"], index=["ppm", "Da"].index(params["eic_mz_unit"]), key="eic_mz_unit"
    )
    c2.number_input("**mass tolerance ppm**", 1, 100,
                    params["eic_tolerance_ppm"], step=5, key="eic_tolerance_ppm")
    c3.number_input(
        "mass tolerance Da", 0.01, 10.0, params["eic_tolerance_da"], 0.05, key="eic_tolerance_da"
    )


    results_dir = Path(st.session_state.workspace,
                       "extracted-ion-chromatograms")

    c1, _, c3 = st.columns(3)
    if c1.form_submit_button("Save Parameters"):
        save_params(params)
        edited.to_csv(path, sep="\t", index=False)
    submitted = c3.form_submit_button("Extract chromatograms", type="primary")

if submitted:
    edited.to_csv(path, sep="\t", index=False)

    mzML_files = [str(Path(st.session_state.workspace,
                        "mzML-files", f+".mzML")) for f in st.session_state["eic_selected_mzML"]]
    if not mzML_files:
        st.warning("Upload/select some mzML files first!")
    else:
        extract_chromatograms(results_dir,
                                mzML_files,
                                edited,
                                st.session_state["eic_mz_unit"],
                                st.session_state["eic_tolerance_ppm"],
                                st.session_state["eic_tolerance_da"],
                                st.session_state["eic_time_unit"],
                                st.session_state["eic_peak_width"],
                                st.session_state["eic_baseline"])


# Display summary table
path = Path(results_dir, "summary.tsv")
if path.exists():
    tabs = st.tabs(["📊 Summary", "📈 Samples", "📈 Metabolites",
                    "📁 Chromatogram data", "📁 Meta data"])
    with open(Path(results_dir, "run-params.txt"), "r") as f:
        baseline = int(f.readline())
        time_unit = f.readline()

    with tabs[0]:
        st.checkbox(
            "combine variants",
            params["eic_combine"],
            help="Combines different variants (e.g. adducts or neutral losses) of a metabolite. Put a `#` with the name first and variant second (e.g. `glucose#[M+H]+` and `glucose#[M+Na]+`)",
            key="eic_combine"
        )
        if st.session_state["eic_combine"]:
            file_name = "summary-combined.tsv"
        else:
            file_name = "summary.tsv"

        df_auc = pd.read_csv(Path(results_dir, file_name), sep="\t").set_index(
            "metabolite"
        )
        # display the feature matrix and it's bar plot
        fig = get_auc_fig(df_auc)
        show_fig(fig, "xic-summary")
        show_table(df_auc, "feature-matrix-xic")

    with tabs[1]:
        # compare two files side by side
        c1, c2 = st.columns(2)
        show_bpc = c1.checkbox("show base peak chromatogram", False)
        show_baseline = c2.checkbox(
            "show baseline for AUC calculation", False)
        file1 = c1.selectbox(f"select file 1", df_auc.columns)

        df = pd.read_feather(Path(results_dir, file1[:-4] + "ftr"))
        if show_baseline:
            df["AUC baseline"] = [baseline] * df.shape[0]
        if not show_bpc:
            df.drop(columns=["BPC"], inplace=True)
        fig = get_sample_plot(df, file1, time_unit)
        with c1:
            show_fig(fig, file1)

        if df_auc.shape[1] > 1:
            file2_options = df_auc.columns.tolist()
            file2_options.remove(file1)
            file2 = c2.selectbox(
                f"select file 2", file2_options)
            df = pd.read_feather(Path(results_dir, file2[:-4] + "ftr"))
            if show_baseline:
                df["AUC baseline"] = [baseline] * df.shape[0]
            if not show_bpc:
                df.drop(columns=["BPC"], inplace=True)
            fig = get_sample_plot(df, file2, time_unit)
            with c2:
                show_fig(fig, file2)

    with tabs[2]:
        # overlayed EICs for each sample
        metabolite = st.selectbox("select metabolite", df_auc.index)
        fig = get_metabolite_fig(df_auc, metabolite, time_unit)
        show_fig(fig, f"xic-{metabolite}")

    with tabs[3]:
        with open(os.path.join(results_dir, "chromatograms.zip"), "rb") as fp:
            btn = st.download_button(
                label="Download chromatogram data",
                data=fp,
                file_name=f"chromatogram-data.zip",
                mime="application/zip",
            )

    with tabs[4]:
        md = pd.DataFrame(
            {
                "filename": df_auc.columns,
                "ATTRIBUTE_Sample_Type": ["Sample"] * df_auc.shape[1],
            }
        ).set_index("filename")
        data = st.data_editor(
            md.T, num_rows="dynamic", use_container_width=True)
        st.download_button(
            "Download Table",
            data.T.to_csv(sep="\t").encode("utf-8"),
            "xic-meta-data.tsv",
        )

save_params(params)