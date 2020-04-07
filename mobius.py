#!/usr/bin/env python3
import os
import re

import click
import numpy as np
import pandas as pd
from google.cloud.storage.client import Client
from tqdm import tqdm

from mobius import graph_process, csv_process, prep_output_folder, text

SVG_BUCKET = "mobility-reports"


def get(filetype="SVG", regex="\d{4}-\d{2}-\d{2}_.+"):
    client = Client.create_anonymous_client()
    blobs = filter(
        lambda b: re.match(f"{filetype}/{regex}", b.name),
        client.list_blobs(SVG_BUCKET),
    )
    return list(blobs)


def get_country(blob, svg):
    name = blob.name.split("/")[-1]
    if svg:
        country = name.split("_")[1]
    else:
        country = name.replace("Mobility_Report_en.pdf", "")[11:-1]
    return country


def show(filetype, svg=True):
    MAXLEN = 20
    blobs = list(get(filetype=filetype))
    print("Available countries:")
    for i, blob in enumerate(blobs):
        country = get_country(blob, svg)
        country = (
            country + (" " * (MAXLEN - len(country)))
            if len(country) < MAXLEN
            else country[:MAXLEN]
        )
        iteration = str(i + 1)
        iteration = (
            iteration
            if (len(iteration) == 3)
            else (" " * (3 - len(iteration)) + iteration)
        )
        print(f" {iteration}. {country} ({blob.name})")


@click.group()
def cli():
    pass


@cli.command(help="List all the SVGs available in the buckets")
def svg():
    show("SVG")


@cli.command(help="List all the PDFs available in the buckets")
def pdf():
    show("PDF", svg=False)


@cli.command()
@click.argument("COUNTRY_CODE")
@click.option(
    "-s", "--svg", help="Download SVG of the country code", is_flag=True, default=True,
)
@click.option(
    "-p", "--pdf", help="Download PDF of the country code", is_flag=True,
)
def download(country_code, svg, pdf):
    client = Client.create_anonymous_client()

    def _download(blobs, svg):
        extension = "svg" if svg else "pdf"

        if len(blobs):
            for blob in blobs:
                with open(f"{extension}s/{get_country(blob, svg)}.{extension}", "wb+") as fileobj:
                    client.download_blob_to_file(blob, fileobj)

            print(f"Download {country_code} {extension} complete. Saved to /{extension}s")
        else:
            print(f"Could not find a {extension} file for code {country_code}")

    if svg:
        regex = f"\d{{4}}-\d{{2}}-\d{{2}}_{country_code}_.+"
        blobs = get(filetype="SVG", regex=regex)
        _download(blobs, True)
    if pdf:
        regex = f"\d{{4}}-\d{{2}}-\d{{2}}_{country_code}_.+"
        blobs = get(filetype="PDF", regex=regex)
        _download(blobs, False)


@cli.command(help="Process a given country SVG")
@click.argument("INPUT_LOCATION")
@click.argument("OUTPUT_FOLDER")
@click.argument("DATES_FILE", default="config/dates_lookup.csv")
@click.option(
    "-f", "--folder", help="If provided will overwrite the output folder name",
)
@click.option(
    "-s", "--svgs", help="Enables saving of svgs that get extracted", is_flag=True,
)
@click.option(
    "-p",
    "--plots",
    is_flag=True,
    help="Enables creation and saving of additional PNG plots",
)
def proc(input_location, output_folder, folder, dates_file, svgs, plots):

    date_lookup_df = pd.read_csv(dates_file)

    print(f"Processing {input_location}")
    output_folder = prep_output_folder(input_location, output_folder, folder)
    data = graph_process(input_location, output_folder, svgs)

    iterable = tqdm(data.items())
    return [
        csv_process(paths, num, date_lookup_df, output_folder, plots=plots, save=True)
        for num, paths in iterable
    ]


@cli.command(help="Combine text extracted from PDF with SVG plot data")
@click.argument("INPUT_PDF")
@click.argument("INPUT_SVG")
@click.argument("OUTPUT_FOLDER")
def knit(input_pdf, input_svg, output_folder, dates_file="config/dates_lookup.csv"):

    def validate(df):
        df.headline = df.headline.str.replace("%", "", regex=False)
        df.loc[df.headline.str.contains("Not enough data", regex=False), "headline"] = np.nan
        df.headline = df.headline.astype(float)
        last_entries = df.dropna().groupby(by=["region", "plot_name"]).tail(1)

        print(f"There are {len(last_entries)} plots with data")

        invalid_df = last_entries[last_entries.value.round() != last_entries.headline]

        print(f"There are {len(invalid_df)} plots where the last data point doesn't match the headline figure")

        print(invalid_df[["country", "region", "plot_name", "value", "headline"]]
        .set_index(["country", "region", "plot_name"]).to_markdown())

    print(f"Knitting {input_pdf} and {input_svg} data together")
    summary_df = text.summarise(input_pdf)

    outfile = os.path.join(output_folder, os.path.splitext(os.path.basename(input_pdf))[0] + "_summary.csv")
    summary_df.to_csv(outfile, index=False)

    data = graph_process(input_svg, None, False)

    date_lookup_df = pd.read_csv(dates_file)

    iterable = tqdm(data.items())
    dfs = [
        csv_process(paths, num, date_lookup_df, output_folder, plots=False, save=True)
        for num, paths in iterable
    ]

    plot_df = pd.concat(dfs)

    result_df = pd.merge(summary_df, plot_df, left_on="plot_num", right_on="graph_num", how="outer")

    final_outfile = os.path.join(output_folder, os.path.splitext(os.path.basename(input_pdf))[0] + ".csv")
    result_df = result_df[[
        "country",
        "region",
        "plot_name",
        "page_num",
        "plot_num",
        "asterisk",
        "date",
        "value",
        "headline",
    ]]

    result_df.to_csv(final_outfile, index=False)

    validate(result_df)


if __name__ == "__main__":
    cli()
