# -*- coding: utf-8 -*-

"""
Parsing and extraction functions
"""
import enum
import re
import json

from datetime import timedelta, datetime

from six.moves import html_parser
from bs4 import BeautifulSoup as BeautifulSoup_

from common import Course, Block, Video, WebPage


# Force use of bs4 with html.parser
BeautifulSoup = lambda page: BeautifulSoup_(page, 'html.parser')


def edx_json2srt(o):
    """
    Transform the dict 'o' into the srt subtitles format
    """
    if o == {}:
        return ''

    base_time = datetime(1, 1, 1)
    output = []

    for i, (s, e, t) in enumerate(zip(o['start'], o['end'], o['text'])):
        if t == '':
            continue

        output.append(str(i) + '\n')

        s = base_time + timedelta(seconds=s/1000.)
        e = base_time + timedelta(seconds=e/1000.)
        time_range = "%02d:%02d:%02d,%03d --> %02d:%02d:%02d,%03d\n" % \
                     (s.hour, s.minute, s.second, s.microsecond/1000,
                      e.hour, e.minute, e.second, e.microsecond/1000)

        output.append(time_range)
        output.append(t + "\n\n")

    return ''.join(output)

#CHANGE: merged everything to one single EdxExtractor

class EdxExtractor(object):

    def extract_username_from_dashboard(self, dashpagecontent):
        #CHANGE: required to get blocks
        soup = BeautifulSoup(dashpagecontent)
        username = soup.find_all('span', 'username')
        return username[0].text

    def extract_courses_from_dashboard(self, dashpagecontent):
        """
        Extracts courses (Course) from the html page
        Originally known as extract_courses_from_html
        """
        soup = BeautifulSoup(dashpagecontent)

        #CHANGE: (not really change) Courses are listed as H3 in the dashboard html

        courses_soup = soup.find_all('article', 'course')
        if len(courses_soup) == 0:
            courses_soup = soup.find_all('article', 'course audit')

        courses = []

        for course_soup in courses_soup:
            course_id = None
            course_name = course_soup.h3.text.strip()
            course_url = None
            course_state = 'Not yet'
            try:
                course_url = course_soup.a['href']
                if course_url.endswith('/home'): #CHANGE: url now starts with learning.edx and ends with /home
                    course_state = 'Started'
                #CHANGE: course id is the key
                course_id = course_soup.a['data-course-key']
            except KeyError:
                pass
            courses.append(Course(id=course_id,
                                  name=course_name,
                                  url=course_url,
                                  state=course_state))

        return courses

    def extract_blocks_from_json(self, jsondict):
        """
        Extract blocks from the json file
        """
        blocks_json = jsondict
        root_id = blocks_json['root']
        blocks_json = blocks_json['blocks']
        all_block_names = list(blocks_json.keys())
        all_blocks = {block_name: Block(position = i, content = blocks_json[block_name])
                     for i, block_name in enumerate(all_block_names, 1)}
        for i in all_blocks:
            all_blocks[i].children = [all_blocks[x] for x in all_blocks[i].childrenid]

        return all_blocks[root_id]

    def extract_units_from_html(self, page, file_formats):
        """
        Extract Units from a vertical
        """
        # in this function we avoid using beautifulsoup for performance reasons
        # parsing html with regular expressions is really nasty, don't do this if
        # you don't need to !
        
        # page itself is a unit!
        units = [WebPage(None, page)]

        video_units = re.compile('(<div.*?id="video_[0-9a-f]*".*?class="video closed".*?>.*?<\/div>)',re.DOTALL)                              
        for video_html in video_units.findall(page):
        
            re_metadata = re.compile(r"data-metadata='(.*?)'")
            match_metadatas = re_metadata.findall(video_html.replace('&#34;','"'))
            for match_metadata in match_metadatas:
                metadata = html_parser.HTMLParser().unescape(match_metadata)
                metadata = json.loads(html_parser.HTMLParser().unescape(metadata))
                units.append(Video(metadata))

        return units

    def extract_subtitle_urls(self, text, BASE_URL):
        re_sub_template_url = re.compile(r'data-transcript-translation-url=(?:&#34;|")([^"&]*)(?:&#34;|")')
        re_available_subs_url = re.compile(r'data-transcript-available-translations-url=(?:&#34;|")([^"&]*)(?:&#34;|")')
        available_subs_url = None
        sub_template_url = None
        match_subs = re_sub_template_url.search(text)

        if match_subs:
            match_available_subs = re_available_subs_url.search(text)
            if match_available_subs:
                available_subs_url = BASE_URL + match_available_subs.group(1)
                sub_template_url = BASE_URL + match_subs.group(1) + "/%s"

        else:
            re_available_subs_url=re.compile(r'href=(?:&#34;|")([^"&]+)(?:&#34;|")&gt;Download transcript&lt;')
            match_available_subs = re_available_subs_url.search(text)
            if match_available_subs:
                sub_template_url = BASE_URL + match_available_subs.group(1)
                available_subs_url = None

        return available_subs_url, sub_template_url

    def extract_mp4_urls(self, text):
        """
        Looks for available links to the mp4 version of the videos
        """
        # mp4 urls may be in two places, in the field data-sources, and as <a>
        # refs This regex tries to match all the appearances, however we
        # exclude the ';' # character in the urls, since it is used to separate
        # multiple urls in one string, however ';' is a valid url name
        # character, but it is not really common.
        re_mp4_urls = re.compile(r'(?:(https?://[^;]*?\.mp4))')
        mp4_urls = list(set(re_mp4_urls.findall(text)))

        return mp4_urls

    def extract_resources_urls(self, text, BASE_URL, file_formats):
        """
        Extract resources looking for <a> references in the webpage and
        matching the given file formats
        """
        formats = '|'.join(file_formats)
        re_resources_urls = re.compile(r'&lt;a href=(?:&#34;|")([^"&]*.(?:' + formats + '))(?:&#34;|")')
        resources_urls = []
        for url in re_resources_urls.findall(text):
            if url.startswith('http') or url.startswith('https'):
                resources_urls.append(url)
            elif url.startswith('//'):
                resources_urls.append('https:' + url)
            else:
                resources_urls.append(BASE_URL + url)

        # we match links to youtube videos as <a href> and add them to the
        # download list
        re_youtube_links = re.compile(r'&lt;a href=(?:&#34;|")(https?\:\/\/(?:www\.)?(?:youtube\.com|youtu\.?be)\/.*?)(?:&#34;|")')
        youtube_links = re_youtube_links.findall(text)
        resources_urls += youtube_links

        return resources_urls




def is_youtube_url(url):
    re_youtube_url = re.compile(r'(https?\:\/\/(?:www\.)?(?:youtube\.com|youtu\.?be)\/.*?)')
    return re_youtube_url.match(url)
