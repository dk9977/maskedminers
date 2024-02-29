"""
Masked Miners
File: maskedminers.py
Author: Derrick Kempster

This module develops off of the asynchronous mining code in Sukhoi. It adds
headers to the HTTP calls for the purpose of masking true identity. The miners
will pretend to be regular users with the most common desktop User-Agent
identities.

To ensure that miners can remain reasonably masked, the "user-agent.json" file
should be updated within a reasonable timeframe. Calling Environment.setup()
will do this. The pool for the "untwisted" module should be empty for this
operation. If not, you may pre-emptively trigger other events. The User-Agents
list can be found here:
https://www.useragents.me/#most-common-desktop-useragents
"""


import gzip
import io
from json import dumps, loads
import lxml.html as LxmlHtml
import os
import random
from sukhoi import Miner, MinerLXML
import sys
import time
from untwisted import core
from websnake import FormData, Response


class UserAgentMiner(MinerLXML):
    """
    A miner for the latest common user-agent data.
    This can safely be done without masking.
    """
    
    def __init__(self, filename:str):
        """
        Constructor.
        :param str filename: The name of the file to update.
        """
        
        self.filename = filename
        url = 'https://www.useragents.me/'
        headers = {
            'connection': 'close',
            'user-agent': 'Updater Bot'
        }
        super().__init__(url, headers)
    
    def setup(self, response:Response):
        """
        Prepare to read the response.
        :param Response response: The HTTP response.
        """
        
        self.response = response
        
        data = response.fd.read()
        response.fd.seek(0)
        if 'transfer-encoding' in response.headers.headers: # server thinks data is too big
            self.handle_chunked(data)                       # but it's still in the response
        else:                                               # normal HTML-reading functionality
            self.build_dom(data)
    
    def run(self, dom):
        """
        Run the miner.
        :param dom: The LXML tree based on the response.
        """
        
        json_str = ''
        
        # Find the data
        section = dom.xpath('//div[@id="most-common-desktop-useragents-json-csv"]')[0]
        type_regions = section.xpath('.//div')
        for region in type_regions:
            type_name = region.xpath('.//h3')[0].text
            if type_name == 'JSON':
                json_str = region.xpath('.//textarea')[0].text
                break
        if json_str == '':  # data not found
            raise ValueError('The JSON data could not be found!')
        
        self.write(json_str)
        self.append(json_str)
        
    def write(self, json_str:str):
        """
        Write the found user-agents data to file.
        :param str json: The JSON data string.
        """
        
        with open(self.filename, 'w') as file:
            file.write(json_str)
            
    def handle_chunked(self, data:bytes):
        """
        When the data will not be LXML-parseable, this runs instead of
        "build_dom" and "run". The data is set to be chunked, but observations
        have shown that the response still contains the desired result. It is
        unknown if this is always the case. If not, this may fail.
        :param bytes data: The content of the response.
        """
        
        data_str = data.decode()    # convert to str
        
        try:    # pick out data
            json_str = data_str.split('<h3>JSON</h3>', 1)[1].split('<textarea', 1)[1].split('>', 1)[1].split('</textarea>', 1)[0]
        except: # unexpected data format!
            print('Unfamiliar response data:', data_str, file=sys.stderr)
            raise NotImplementedError('The user-agents data could not be found!')
        
        self.write(json_str)
        self.append(json_str)


class Browser:
    """
    A browser used by an emulated environment.
    """
    
    NONE = 0
    CHROME = 1
    EDGE = 2
    FIREFOX = 3
    OPERA = 4
    SAFARI = 5
    
    __brands = [None, 'Google Chrome', 'Microsoft Edge', None, 'Opera', None]
    __keywords = ['', 'Chrome', 'Edg', 'Firefox', 'OPR', 'Safari']
    
    def __init__(self, ua:str):
        """
        Constructor.
        :param str ua: A user-agent string.
        """
        
        self.type = Browser.NONE    # an integer representing a type of browser
        self.version = -1           # remains -1 when the browser is unknown
        self.chromium_version = -1  # remains -1 when the browser is not known to use chromium
        
        # Determine browser indicated by the user-agent
        k = self.__keywords[Browser.FIREFOX]
        i = ua.find(k)
        if i >= 0:  # indicates Firefox
            self.type = Browser.FIREFOX
            self.version = int(ua[i + len(k) + 1:].split('.', 1)[0])
        else:
            for b in [Browser.EDGE, Browser.OPERA]:
                k = self.__keywords[b]
                i = ua.find(k)
                if i >= 0:  # indicates Edge or Opera
                    self.type = b
                    self.version = int(ua[i + len(k) + 1:].split('.', 1)[0])
                    break
            k = self.__keywords[Browser.CHROME]
            i = ua.find(k)
            if i >= 0:  # indicates usage of Chromium
                self.chromium_version = int(ua[i + len(k) + 1:].split('.', 1)[0])
                if self.type == Browser.NONE:   # indicates Chrome
                    self.type = Browser.CHROME
                    self.version = self.chromium_version
            else:
                k = self.__keywords[Browser.SAFARI]
                i = ua.find(k)
                if i >= 0:  # indicates Safari
                    self.type = Browser.SAFARI
                    self.version = int(ua[i + len(k) + 1:].split('.', 1)[0])
        
        # Set branding data
        if self.uses_chromium():    # needs branding
            misc = ['', ' ', '_', ';', '(', ')']    # assumed from observations
            fake_brand = f'{random.choice(misc)}Not{random.choice(misc)}A{random.choice(misc)}Brand'    # assumed from observations
            fake_version = random.randint(1, 100)   # assumed from observations
            brands = [
                (fake_brand, fake_version),
                (self.__brands[self.type], self.version),
                ('Chromium', self.chromium_version)
            ]
            random.shuffle(brands)  # not yet observed, but follows documentation
            self.branding = ', '.join(list(map(lambda brand: f'"{brand[0]}"; v="{brand[1]}"', brands)))
        else:
            self.branding = ''  # unused
    
    def uses_chromium(self) -> bool:
        """
        Tells whether this browser type uses Chromium.
        :returns bool: Whether chromium is used.
        """
        
        return self.chromium_version >= 0


class Platform:
    """
    A platform operated upon by an emulated browser.
    """
    
    def __init__(self, ua:str):
        """
        Constructor.
        :param str ua: A user-agent string.
        """
        
        self.type:str           # type of platform
        self.os = ''            # operating system
        self.os_version = ''    # version of operating system
        
        if len(ua) > 0:
            self.is_mobile = False
            system_info = ua.split('(', 1)[1].split(')', 1)[0]
            if 'Windows' in system_info:
                self.type = system_info.split(';', 1)[0]
                self.os, self.os_version = system_info.split(' ', 1)
            elif 'Macintosh' in system_info:    # unverified random guess
                self.type = 'Macintosh'
                self.os, self.os_version = system_info.split('; ', 1)[1].rsplit(' ', 1)
            elif 'X11' in system_info:          # unverified random guess
                self.type = 'Linux'
                self.os = system_info.split(' ', 2)[1].strip(';')
            else:                               # some new unparseable case
                print(f'System info section of user-agent cannot be parsed! ({system_info})', sys.stderr)
                self.type = ua.split(' ', 1)[0]
        else:                                   # empty
            print('The user-agent is empty!', sys.stderr)


class Environment:
    """
    An emulated environment for masking.
    Also holds all potential user-agents.
    """
    
    __SEC_DAY = 86400               # seconds per day
    __UA_FILE = 'user-agent.json'   # file holding user-agent data
    updated = False                 # whether the user-agents have been updated
    ready = False                   # whether the user-agents have been loaded
    uas:list                        # storage for user-agent options
    pcts:list                       # stores probabilities of the user-agents
    
    def __init__(self):
        """
        Constructor for a random common environment.
        """
        
        if not Environment.ready:   # if not pre-loaded
            content:str
            with open(Environment.__UA_FILE, 'r') as file:
                content = file.readline()
            Environment.load_content(content)
        
        # Set fields
        self.ua = random.choices(self.uas, self.pcts)[0]
        self.browser = Browser(self.ua)
        self.platform = Platform(self.ua)
        
    def load_content(content:str):
        """
        Fill user-agents' and probabilities' storages from JSON data.
        :param str content: A JSON string with the data.
        """
        
        agents = loads(content)
        Environment.uas = list(map(lambda agent: agent['ua'], agents))
        Environment.pcts = list(map(lambda agent: agent['pct'], agents))
        Environment.ready = True
    
    def needs_update() -> bool:
        """
        Tells whether Environment should be updated.
        A day-old (or older) user-agents data file should be updated.
        :returns bool: Whether update is needed.
        """
        
        if Environment.updated:
            return False
        last_update = os.path.getmtime(Environment.__UA_FILE)
        yesterday = time.time() - Environment.__SEC_DAY
        return last_update < yesterday
    
    def update():
        """
        Updates the user-agents data file.
        Only run when the pool for the "untwisted" module is empty.
        """
        
        miner = UserAgentMiner(Environment.__UA_FILE)
        core.gear.mainloop()
        content = miner[0]
        Environment.load_content(content)   # pre-loads
        Environment.updated = True

    def setup(force:bool = False) -> bool:
        """
        Update when necessary.
        Only run when the pool for the "untwisted" module is empty.
        :param bool force: Whether to force an update.
        :returns bool: Whether the update occurred.
        """
        
        if force or Environment.needs_update():
            Environment.update()
            return True
        return False


class MaskedMiner(Miner):
    """
    A Miner that masks itself with headers.
    """
    
    def __init__(self, url:str, headers:dict = {}, method='get', payload:dict = None, attempts=5, environment:Environment = None):
        """
        Constructor.
        :param str url: The URL to mine.
        :param dict headers: The headers for the request.
        :param str method: The type of request to send.
        :param dict payload: The data to send in a POST request.
        :param int attempts: The number of times to attempt the request.
        :param Environment environment: The emulated environment for the calls, used to set header data.
        """
        
        if environment is None:
            self.environment = Environment()
        else:
            self.environment = environment
        
        # Headers
        headers.setdefault('accept-language', 'en-US,en;q=0.9')
        headers.setdefault('dnt', '1')
        headers.setdefault('user-agent', self.environment.ua)
        if self.environment.browser.uses_chromium():
            headers.setdefault('sec-ch-ua', self.environment.browser.branding)
            headers.setdefault('sec-ch-ua-mobile', f'?{int(self.environment.platform.is_mobile)}')
            headers.setdefault('sec-ch-ua-platform', f'"{self.environment.platform.type}"')
        else:
            for header in list(headers.keys()):
                if header.lower().startswith('sec-'):
                    del headers[header]
        
        # Payload
        form = self.form_payload(payload)
            
        super().__init__(url, headers, {}, method, form, None, attempts)
    
    def setup(self, response:Response):
        """
        Prepare to read the response.
        :param Response response: The HTTP response.
        """
        
        self.response = response
        
        data = response.fd.read()                   # get encoded content
        response.fd.seek(0)                         # allow to get again later
        encoding = response.header_encoding()       # determine encoding
        if encoding is not None:                    # data needs decoding
            try:                                    # attempt to get text
                temp = data.decode(encoding)        # will fail on extra encoding layer like gzip (assumed)
                data = temp
            except UnicodeDecodeError:              # still gzip encoded (in observations)
                data = self.backup_decoding(data)
        else:
            data = str(data)
        
        self.build_dom(data)
    
    def backup_decoding(self, data:bytes) -> str:
        """
        If decoding fails, try this instead.
        This assumes that the data is still gzip encoded.
        :param bytes data: Encoded input.
        :returns str: Decoded output.
        """
        
        s:str
        buf = io.BytesIO(data)
        with gzip.GzipFile(fileobj=buf) as f:
            s = f.read().decode('utf-8')         # decode gzip to text
        return s
    
    def form_payload(self, dict_payload:dict) -> FormData:
        """
        Transform a dict payload to a FormData instance.
        FormData is the payload type required by the "websnake" module.
        """
        
        if dict_payload is None:
            return None
        prep_payload = dict(zip(dict_payload, map(dumps, dict_payload.values())))
        return FormData(prep_payload)


class MaskedMinerJSON(MaskedMiner):
    """
    A MaskedMiner for HTTP endpoints that provide JSON responses.
    """
    
    def __init__(self, url, headers:dict = {}, method='get', payload:dict = None, attempts=5, environment:Environment = None):
        """
        Constructor.
        :param str url: The URL to mine.
        :param dict headers: The headers for the request.
        :param str method: The type of request to send.
        :param dict payload: The data to send in a POST request.
        :param int attempts: The number of times to attempt the request.
        :param Environment environment: The emulated environment for the calls, used to set header data.
        """
        
        headers.setdefault('accept', 'application/json')
        headers.setdefault('accept-encoding', 'gzip, deflate, br')
        super().__init__(url, headers, method, payload, attempts, environment)
    
    def build_dom(self, data:str):
        """
        Read the response content for mining.
        :param str data: A string containing the JSON data.
        """
        
        dom = loads(data)
        self.run(dom)


class MaskedMinerLXML(MaskedMiner):
    """
    A MaskedMiner for HTTP endpoints that provide HTML responses.
    """
    
    def __init__(self, url, headers:dict = {}, method='get', payload:FormData = None, attempts=5, environment:Environment = None):
        """
        Constructor.
        :param str url: The URL to mine.
        :param dict headers: The headers for the request.
        :param str method: The type of request to send.
        :param FormData payload: The data to send in a POST request.
        :param int attempts: The number of times to attempt the request.
        :param Environment environment: The emulated environment for the calls, used to set header data.
        """
        
        headers.setdefault('accept', 'text/html')
        headers.setdefault('accept-encoding', 'gzip, deflate, br')
        super().__init__(url, headers, method, payload, attempts, environment)
    
    def build_dom(self, data:str):
        """
        Build the data structure with LXML from the response content.
        :param str data: A string containing the HTML text.
        """
        
        dom = LxmlHtml.fromstring(data)
        self.run(dom)
        

if __name__ == '__main__':
    Environment.update()
