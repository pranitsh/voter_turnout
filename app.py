"""Online document gathering toolkit

Benchmarks:
    https://github.com/py-pdf/benchmarks
"""


import pypdfium2 as pdfium
import os
import requests
import pathlib
import textract
from urllib.parse import quote_plus
from urllib.parse import urlparse
import urllib
import functions_framework
import json
import shutil
import vertexai
from vertexai.preview.generative_models import GenerativeModel, Part
import re
from google.cloud import firestore
import subprocess
import streamlit as st


def find_urls(query, cx, num_results=3):
    """Fetches company links from Google's Custom Search JSON API.

    Args:
        query (str): The company name to search for.
        cx (str): Your Custom Search Engine ID.
        num_results (int, optional): Maximum number of results to return. Defaults to 10.

    Returns:
        list: A list of company links found in the search results.

    Example:
        >>> query = "Levi Strauss and Co."
        >>> cx = st.secrets["custom"]
        >>> find_urls(query, cx)[0]
        'https://www.levistrauss.com/'
    """
    query = quote_plus(query)
    url = f'https://www.googleapis.com/customsearch/v1?key={st.secrets["access"]}&cx={st.secrets["custom"]}&q={query}&num={num_results}'

    response = requests.get(url)
    data = response.json()

    links = []
    for item in data.get('items', []):
        links.append(item['link'])

    return links


def generalize_url(url: str) -> str:
    """Converts a URL to a generalized link format.

    This function takes a URL as input and returns a generalized link in the format "[domain.com/](https://domain.com/)*".

    Args:
        url (str): The URL to generalize.

    Returns:
        str: The generalized link.

    Raises:
        ValueError: If the input is not a valid URL.

    Examples:
        >>> generalize_url('https://www.levistrauss.com/')
        'levistrauss.com'
        >>> generalize_url("https://www.apple.com/")
        'apple.com'
    """
    parsed_url = urlparse(url)

    if not all([parsed_url.scheme, parsed_url.netloc]):
        raise ValueError("Invalid URL")

    shortened_url = '.'.join(parsed_url.netloc.split('.')[-2:])

    return f"{shortened_url}"


def find_documents(topic, query, cx, filetypes=["pdf", "csv", "txt"], num_results=5):
    """
    Performs a custom Search for documents of specific file types on the topic.

    Args:
        topic (str): The main topic.
        query (str): The search query.
        cx (str): Your Google Custom Search Engine ID.
        filetypes (list, optional): List of file types to search for (e.g., ["pdf", "docx"]). Defaults to ["pdf", "docx", "pptx", "xlsx", "txt"].
        sites (list, optional): List of websites to search within (e.g., ["*.apple.com"]). Defaults to ["*.apple.com"].
        num_results (int, optional): The maximum number of search results to return. Defaults to 10.

    Returns:
        dict: The JSON response from the Google Custom Search API.

    Example:
        >>> query = "Levi Strauss and Co."
        >>> cx = st.secrets["custom"]
        >>> len(find_documents(query, "Environmental Consumer Report", cx)) == 5
        True
    """
    filetype_query = " OR ".join([f"filetype:{ft}" for ft in filetypes])
    search = quote_plus(f"{topic} {query} ({filetype_query})")
    url = f'https://www.googleapis.com/customsearch/v1?key={st.secrets["access"]}&cx={st.secrets["custom"]}&q={search}&num={num_results}'
    response = requests.get(url)
    data = response.json()
    links = []
    for item in data.get('items', []):
        links.append(item['link'])
    return links


def read_pdf(file) -> str:
    """`read_pdf` reads and returns the text of the pdf file

    Args:
        file: accepts path strings, bytes, and byte buffers

    Returns:
        The string output of the pdf

    Example:
        >>> file = "data/random_text.docx"
        >>> print(process_file(file)[:12])
        Random Text
        <BLANKLINE>
    """
    pdf = pdfium.PdfDocument(file)
    text = ""
    for i in range(len(pdf)):
        page = pdf[i]
        textpage = page.get_textpage()
        text += "\n" + textpage.get_text_bounded()
    return text


def process_file(file):
    """`process_file` reads and returns the text of the file

    Args:
        file: accepts path strings, bytes, and byte buffers

    Returns:
        The string output of the pdf

    Example:
        >>> file = "data/random_text.docx"
        >>> print(process_file(file)[:12])
        Random Text
        <BLANKLINE>
    """
    file_name = pathlib.Path(file)
    try:
        if file_name.suffix == ".pdf":
            return read_pdf(file)
        elif file_name.suffix == ".docx" or file_name.suffix == ".csv" or file_name.suffix == ".epub" or file_name.suffix == ".json" or file_name.suffix == ".html" or file_name.suffix == ".odt" or file_name.suffix == ".pptx" or file_name.suffix == ".txt" or file_name.suffix == ".rtf":
            result_str: str = textract.process(file)
            return result_str.decode('utf_8', errors="ignore")
    except:
        pass


def process_file_questions(urls, question, temp_dir="temp"):
    """
    Downloads files from a list of URLs to a temporary directory.

    Args:
        urls (list): List of URLs to download.
        temp_dir (str, optional): Path to a specific temporary directory. If None, a new one is created.

    Returns:
        list: List of file paths where the downloaded files are stored.
    
    Example:
        >>> urls = ['https://levistrauss.com/wp-content/uploads/2022/09/2021-Sustainability-Report-Summary-.pdf']
        >>> links, summaries = process_file_questions(urls, "What are the key impacts of this company?")
        >>> len(summaries[0]) > 0
        True
    """
    links = []
    summaries = []
    path = os.path.abspath('temp')
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs('temp', exist_ok=True)
    for url in urls:
        try:
            response = requests.get(url)
            # response.raise_for_status()  # Raise an exception for HTTP errors
            filename = os.path.basename(url)  # Extract filename from URL
            filepath = os.path.join(path, filename)
            with open(filepath, 'wb') as f:
                f.write(response.content)
            summary = pdf_answerer(question, filepath, st.secrets["project"])
            links.append(url)
            summaries.append(summary)
        except:
            print(f"Error downloading {url}")
    shutil.rmtree(path, ignore_errors=True)
    return links, summaries


def numbers_split(s):
    """
    Splits the input string on any character that is not a number,
    and returns a list of integers that were found in the string.

    Examples:
    >>> numbers_split('1, 2, 3, 4')
    [0, 1, 2, 3]
    >>> numbers_split('a1b2c3')
    [0, 1, 2]
    >>> numbers_split('no numbers here')
    []
    >>> numbers_split('abc123def456')
    [122, 455]
    >>> numbers_split('10.5 and 11.0')
    [9, 4, 10]
    """
    parts = re.split(r'\D+', s)
    parts = [int(part) for part in parts if part.isdigit()]
    parts = [num-1 for num in parts if num != 0]
    return parts


def split_pdf(input_pdf_path, output_pdf_path, page_numbers):
    """
    Splits a PDF and creates a new PDF composed of specified pages from the original PDF.

    Args:
        input_pdf_path (str): Path to the input PDF file.
        output_pdf_path (str): Path to save the output PDF file.
        page_numbers (list of int): List of page numbers to extract (0-based index).

    Examples:
    >>> split_pdf('data/random_text.pdf', 'temp/random_text-new.pdf', [1, 2])
    [1]
    """
    pdf = pdfium.PdfDocument(input_pdf_path)
    len_pdf = len(pdf)
    page_numbers = [page for page in page_numbers if 0 <= page < len_pdf]

    new_pdf = pdfium.PdfDocument.new()
    os.makedirs('temp', exist_ok=True)
    
    new_pdf.import_pages(pdf, page_numbers, 0)
    new_pdf.save(output_pdf_path)
    return page_numbers


def add_suffix_to_filepath(filepath, suffix="-new"):
    """
    Adds a suffix to the file name before the file extension.

    Args:
        filepath (str): The original file path.
        suffix (str): The suffix to add to the file name.

    Returns:
        str: The new file path with the suffix added.

    Examples:
    >>> add_suffix_to_filepath("test.pdf")
    'temp\\\\test-new.pdf'
    >>> add_suffix_to_filepath("/path/to/test.pdf")
    'temp\\\\test-new.pdf'
    >>> add_suffix_to_filepath("document.txt", "_v2")
    'temp\\\\document_v2.txt'
    """
    directory, filename = os.path.split(filepath)
    name, ext = os.path.splitext(filename)
    new_filename = f"{name}{suffix}{ext}"
    os.makedirs('temp', exist_ok=True)
    return os.path.join('temp', new_filename)


def pdf_answerer(question: str, pdf_location: str, project_id: str) -> list[str]:
    """
    Example:
        >>> project_id = st.secrets["project"]
        >>> pdf_location = "data/random_text.pdf"
        >>> response = pdf_answerer("How many times is random text repeated?", pdf_location, project_id)
        >>> len(response) > 0
        True
    """
    vertexai.init(project=project_id, location="us-central1")
    try:
        file_bytes = pathlib.Path(pdf_location).read_bytes()
        pdf_file = Part.from_data(file_bytes, mime_type="application/pdf")
        generative_multimodal_model = GenerativeModel("gemini-1.5-flash-001")
        page_response = generative_multimodal_model.generate_content([
            pdf_file, 
            question,
            "Be thorough. Include all relevant context of the question, the document, and anything else in the answer. Use numbers and statistics."
        ])
        return page_response.text
    except:
        return ""


def runner(topic, query, question):
    """
    Example:
        >>> links, responses = runner("Provincetown MA 2024", "Local Election Voter Turnout", "How many people turned out this election?")
        54125447
        >>> print(type(response))
        <class 'list'>
    """
    cx = st.secrets["custom"]
    links = find_documents(topic, query, cx=cx, num_results=5)
    print(links)
    links, summaries = process_file_questions(links, question)
    return links, summaries


def main():
    st.set_page_config(page_title="Voter Turnout Query", page_icon="🗳️")

    st.sidebar.title('Navigation')
    st.sidebar.radio("Go to", ['Voter Turnout'], index=0)

    st.title("Voter Turnout Query 🗳️")
    st.subheader("Find Voter Turnout for Different Elections")
    st.write("Welcome! This tool helps you find voter turnout for different types of elections such as state elections, federal elections, presidential elections, local elections, and more. Simply enter the type of election and location, and we'll do the rest!")

    st.markdown("### Enter the location and type of election to find out the voter turnout.")

    location = st.text_input("Enter the location of the election and/or year:")
    election_type = st.text_input("Enter the type of election (e.g., state election, federal election, presidential election, local election):")
    submit = st.button("Get Voter Turnout")

    if submit:
        if election_type:
            with st.spinner("Fetching Voter Turnout Data..."):
                links, responses = runner(location, election_type + " Voter Turnout", "What is the voter turnout?")
                for idx, (link, summary) in enumerate(zip(links, responses)):
                    st.text_area(f"Voter Turnout Data {idx+1}", f"{link}\n\n{summary}", height=200)


if __name__ == "__main__":
    # import doctest
    # doctest.testmod()
    main()
