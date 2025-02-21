'''
RemedyBG debugger updater for 10x (10xeditor.com) 
Original Script author: RetroZelda

Setup and Initialization:
    
    Requires the following python modules to be installed:
        - requests
        - BeautifulSoup4
        
        To install these modules in 10x's python use the pip command with python3 and set  
        the target to be 10x's installation directory.  You may need to run cmd/ps as admin
            Example:    python3 -m pip install --target="C:\Program Files\PureDevSoftware\10x\Lib\site-packages" requests
                        python3 -m pip install --target="C:\Program Files\PureDevSoftware\10x\Lib\site-packages" BeautifulSoup4
    
    These are also required, but should already be part of 10x      
          - os
          - json
          - shutil
          - zipfile
          - tempfile
          
    Make sure you have the following settings filled out:
        - RemedyBG_Updater.PortalToken
        - RemedyBG_Updater.ItchLoginCookie
        - RemedyBG_Updater.ItchLoginToken
        
        You can get the Portal Token from the itch.io download page url for RemedyBG.  
            - in any browser login to itch.io
            - navigate to https://remedybg.itch.io/remedybg
            - if you havnt purchased RemedyBG, do so now.  Support the dev!
            - click the "Download" button
            - The PortalToken value will be in the url for the downloads page
                e.g: https://remedybg.itch.io/remedybg/download/{PortalToken}
    
        You can get the Itch.io Login Cookie and Token by reading the saved cookies via your browser
            - in chorome login to itch.io
            - press f12 and go to the "application" tab
            - under "storage" expand "Cookies"
            - use the "itchio" value for RemedyBG_Updater.ItchLoginCookie
            - use the "itchio_token" value for RemedyBG_Updater.ItchLoginToken
            
    if you have the above Requirements satisfied, you can simply run the command `RDBG_setup` or `RDBG_update_latest` to get RemedyBG setup

Options:
    - RemedyBG.Path: Path to remedybg.exe. If not set, please run RDBG_setup
    
    - RemedyBG_Updater.PortalToken: unique token seen in the URL of the RemedyBG itch.io page
    - RemedyBG_Updater.ItchLoginCookie:	itch.io saved login cookie
    - RemedyBG_Updater.ItchLoginToken: itch.io saved session token
    
    - RemedyBG_Updater.StartPage: page to start at when scraping the forums for updates
    - RemedyBG_Updater.PagesToScan: will scrape until we go through this number of forum pages.  Generally a low value(2) is fine as the forum isnt too active
    - RemedyBG_Updater.MaxVersionHistory: will scrape until we find this number of versions
    
    - RemedyBG_Updater.UpdateOnBoot: Check for updates when this script is (re)loaded
    
Commands:
    - RDBG_setup:           Setup remedy BG to be handled by this script 
    - RDBG_version:         Check if you are on the latest version
    - RDBG_update_latest:   Updates to the latest version

History:
  0.1.2
    - Update to handle new forum layout for version scanning
    - getting settings values will include quotes around strings.  Ensure those quotes arent included
  0.1.1
    - Removed os calls that 10x had permission problems with
    - utilize tempfile instead of C:/tmp
  0.1.0
    - First release
'''

from N10X import Editor
import os
import shutil
import json
import zipfile
import requests
import tempfile
from bs4 import BeautifulSoup

TITLE:str = "RemedyBG Updater"

def create_all_settings():
    Editor.SetSetting("RemedyBG_Updater.PortalToken", "")
    Editor.SetSetting("RemedyBG_Updater.ItchLoginCookie", "")
    Editor.SetSetting("RemedyBG_Updater.ItchLoginToken", "")
    
    Editor.SetSetting("RemedyBG_Updater.StartPage", 1)
    Editor.SetSetting("RemedyBG_Updater.PagesToScan", 2)
    Editor.SetSetting("RemedyBG_Updater.MaxVersionHistory", 3)
    Editor.SetSetting("RemedyBG_Updater.UpdateOnBoot", false)
    
def create_missing_settings():

    if Editor.GetSetting("RemedyBG_Updater.PortalToken") == "":
        log("'RemedyBG_Updater.PortalToken' is missing,  Setting to default.")
        Editor.SetSetting("RemedyBG_Updater.PortalToken", "")        
        
    if Editor.GetSetting("RemedyBG_Updater.ItchLoginCookie") == "":
        log("'RemedyBG_Updater.ItchLoginCookie' is missing,  Setting to default.")
        Editor.SetSetting("RemedyBG_Updater.ItchLoginCookie", "")
        
    if Editor.GetSetting("RemedyBG_Updater.ItchLoginToken") == "":
        log("'RemedyBG_Updater.ItchLoginToken' is missing,  Setting to default.")
        Editor.SetSetting("RemedyBG_Updater.ItchLoginToken", "")    
        
    if Editor.GetSetting("RemedyBG_Updater.StartPage") == "":
        log("'RemedyBG_Updater.StartPage' is missing,  Setting to default.")
        Editor.SetSetting("RemedyBG_Updater.StartPage", 1)
        
    if Editor.GetSetting("RemedyBG_Updater.PagesToScan") == "":
        log("'RemedyBG_Updater.PagesToScan' is missing,  Setting to default.")
        Editor.SetSetting("RemedyBG_Updater.PagesToScan", 2)
        
    if Editor.GetSetting("RemedyBG_Updater.MaxVersionHistory") == "":
        log("'RemedyBG_Updater.MaxVersionHistory' is missing,  Setting to default.")
        Editor.SetSetting("RemedyBG_Updater.MaxVersionHistory", 3)   
        
    if Editor.GetSetting("RemedyBG_Updater.UpdateOnBoot") == "":
        log("'RemedyBG_Updater.UpdateOnBoot' is missing,  Setting to default.")
        Editor.SetSetting("RemedyBG_Updater.UpdateOnBoot", false)   

def debug_log(text):        
    output_debug_text = Editor.GetSetting("RemedyBG.OutputDebugText")
    if output_debug_text:
        print('RDBG: [debug] {text}'.format(text=text))

def log(text):        
    print('RDBG: [log] {text}'.format(text=text))
    
# use to check for new versions of RemedyBG
class VersionChecker:    
    def __init__(self):
    
        create_missing_settings() # do we want to do this here?
        
        # to scrape for changelogs
        self.forum_url = "https://remedybg.handmade.network/forums/{page}" # link to the forum where RemedyBG posts new version changelogs
        
        # to connect to itch.io to download latest versions
        self.portal_url = "https://remedybg.itch.io/remedybg/download/{portal_token}" # link to the RemedyBG itch.io download page
        self.download_url = "https://remedybg.itch.io/remedybg/file/{file_id}?source=game_download&key={portal_token}"
        
        self.portal_url_token   = Editor.GetSetting("RemedyBG_Updater.PortalToken").strip('"').strip("'")
        self.itch_io            = Editor.GetSetting("RemedyBG_Updater.ItchLoginCookie").strip('"').strip("'")
        self.itch_io_token      = Editor.GetSetting("RemedyBG_Updater.ItchLoginToken").strip('"').strip("'")
        
        # forum-scrape settings
        self.page_start = int(Editor.GetSetting("RemedyBG_Updater.StartPage"))
        self.pages_to_scan = int(Editor.GetSetting("RemedyBG_Updater.PagesToScan"))
        self.versions_to_find = int(Editor.GetSetting("RemedyBG_Updater.MaxVersionHistory"))
        
        # local version tracking
        self.local_version = []
        self.latest_version = []
        
        # scraped results
        self.forum_data = []
            
    # gets the forum post content text which will usually contain the changelog of RemedyBG
    def get_post_text(self, post_url:str)->str:
    
        page_raw = requests.get(post_url)        
        soup = BeautifulSoup(page_raw.text, 'html.parser')
        post_content = soup.find("div", {"class": "post-content"})
        
        return post_content.text

    # scrapes the forum to attempt to get the latest version
    def scrape_forum(self):
    
        self.forum_data.clear()
        
        for page_count in range(self.pages_to_scan):
            cur_page = self.page_start + page_count
            cur_url = self.forum_url.format(page=cur_page)
            
            page_raw = requests.get(cur_url)
            debug_log("[ForumScrape] url: {url}".format(url=cur_url))
            
            soup = BeautifulSoup(page_raw.text, 'html.parser')
            forum_posts = soup.find_all("div", {"class": "title nowrap truncate"})
            for forum_post in forum_posts:
            
                title_split = forum_post.text.split(" ")
                if title_split[0] == "RemedyBG":
                    title = title_split[0]
                    version = title_split[1].split(".")
                    if len(version) == 4:
                        url = forum_post.find("a").attrs['href']
                        post_text = self.get_post_text(url)
                        debug_log("[ForumScrape] {title}".format(title=title_split))
                        post = {
                            'post_title': title,
                            'post_version': version,
                            'post_url': url,
                            'post_content': post_text
                        }

                        self.forum_data.append(post)
                        if len(self.forum_data) >= self.versions_to_find:
                            break
            
        if len(self.forum_data) == 0:
            log('[ForumScrape] No versioning data found on forums.')
            return
            
        self.latest_version = self.forum_data[0]['post_version']
        debug_log('[ForumScrape] latest version: {version}'.format(version=".".join(self.latest_version)))
        
    # parse the 10x settings to attempt to get the current version
    # NOTE: This assumes RemedyBG is inside of a folder with its version number
    #       and will fail if not.  Failure will always assume an update is ready
    #
    #       Generally we just want the folder to have the same naming convention 
    #       as the RemedyBG zip file: remedybg_{version}.zip where {version} is a _ delimited series of ints
    #           e.g. 'remedybg_0_3_8_2.zip'
    def determine_installed_version(self):
        remedy_path = Editor.GetSetting("RemedyBG.Path")
        
        remedy_path = os.path.normpath(remedy_path).split(os.sep)[-2]
        remedy_version = remedy_path.split("_")[1:]
        
        debug_log('[LocalScan] Remedy Path: {path}'.format(path=remedy_path))
        debug_log('[LocalScan] Remedy Version: {version}'.format(version=remedy_version))
        self.local_version = remedy_version
        
    # this will attempt to download the latest version from the itch.io page
    # right now this function will require the proper url stuff to be set for your itch.io account.  
    # Buy RemedyBG to support the dev; dont be cheap.
    # TODO: Error handling.  im lazy.  
    def download_latest(self):        
        # lets attempt to read the itch.io page
        cookies = {
        'itchio_token': self.itch_io_token,
        'itchio': self.itch_io
        }
        download_portal_url = self.portal_url.format(portal_token=self.portal_url_token)
        page_raw = requests.get(download_portal_url, cookies=cookies)
                
        soup = BeautifulSoup(page_raw.text, 'html.parser')        
        downloadable_objs = soup.find_all("div", {"class": "upload"})
        for downloadable in downloadable_objs:
            file_name = downloadable.find("div", {"class": "upload_name"}).find("strong", {"class": "name"}).text

            file_id = downloadable.find("a", {"class": "button download_btn"}).attrs['data-upload_id']
            debug_log("[ItchDownloader] Found File: {download_id} - {filename}".format(download_id = file_id, filename=file_name))
            
            file_version = file_name.split(".")[0].split("_")[1:]
            if file_version == self.latest_version:
                log("found latest!")
                file_url = self.download_url.format(file_id=file_id, portal_token=self.portal_url_token)
                
                log("putting in file request: {file_url}".format(file_url=file_url))
                file_request_result = requests.post(file_url, cookies=cookies)
                
                # extract the json result to get our url of the file
                log(file_request_result)
                json_result = json.loads(file_request_result._content)
                
                # download the file
                final_file_url = json_result['url']
                log('Grabbing file from: {url}'.format(url=final_file_url))
                file_request = requests.get(final_file_url, cookies=cookies, stream=True)                
                file_request.raw.decode_content = True
                
                # save the file
                with tempfile.NamedTemporaryFile(mode='wb', suffix="_" + file_name, delete=False) as file_out:
                    final_file = file_out.name;
                    log("saving: " + final_file)
                    shutil.copyfileobj(file_request.raw, file_out)
                        
                    # extract the file
                    remedy_path = Editor.GetSetting("RemedyBG.Path") 
                    parent_path = os.sep.join(os.path.normpath(remedy_path).split(os.sep)[0:-2])
                    
                    destination_dir = os.sep.join([parent_path, file_name.split('.')[0]])
                    log("extracting to: " + destination_dir)
                    with zipfile.ZipFile(final_file, 'r') as zip_ref:
                        zip_ref.extractall(destination_dir)
                    
                    # refresh our local state
                    destination_dir = os.sep.join([destination_dir, "remedybg.exe"])
                    log("Updating 'RemedyBG.Path' Setting: " + destination_dir)
                    Editor.SetSetting("RemedyBG.Path", destination_dir)
                    
                    # 10x doesnt have permission to do this.
                    # remedy_path = os.sep.join(os.path.normpath(remedy_path).split(os.sep)[0:-1]) # this removes the exe name; we want to remove the folder it is in
                    # if os.path.exists(remedy_path):
                    #     log("Removing old 'RemedyBG.Path' path: " + remedy_path)
                    #     os.remove(remedy_path)
                    
                log("done.")
                return

def HandleCommandPanelCommand(command):
    
    if command == "RDBG_setup":
    
        version_checker = VersionChecker()
        
        appdata_folder = os.sep.join(Editor.GetSettingsFolderPath().split('/')[0:-1])
        log(appdata_folder)
        
        # scrape to get the latest version
        log("Checking latest version.")
        version_checker.scrape_forum()
        
        # hackily setup our remedy dir
        remedy_path = os.sep.join([appdata_folder, "RemedyBG", "remedybg_0_0_0_0", "remedybg.exe"])
        Editor.SetSetting("RemedyBG.Path", remedy_path)
        
        log("Attempting to download Version {latest}".format(latest=".".join(version_checker.latest_version)))        
        version_checker.download_latest()
        
        return True
    
    if command == "RDBG_version":
    
        version_checker = VersionChecker()
        log("Checking local version.")
        version_checker.determine_installed_version()
        
        # scrape the forum to determine the latest version
        log("Checking latest version.")
        version_checker.scrape_forum()
        
        debug_log("LatestVersion: {version}".format(version=version_checker.latest_version))
        debug_log("LocalVersion: {version}".format(version=version_checker.local_version))
        if version_checker.latest_version > version_checker.local_version:
            message = "{latest_changes}\n{separator}\n\nLocal Version: {local}\nLatest Version: {latest}\n\nRun 'RDBG_update_latest' command to update.".format(
                latest=".".join(version_checker.latest_version), 
                local=".".join(version_checker.local_version),
                separator="----------------------------------------------------------------------------",
                latest_changes=version_checker.forum_data[0]['post_content'])
            Editor.ShowMessageBox(TITLE, message)
        else:
            message = "Local Version: {local}\nLatest Version: {latest}\n{separator}\n\n{latest_changes}".format(
                latest=".".join(version_checker.latest_version), 
                local=".".join(version_checker.local_version),
                separator="----------------------------------------------------------------------------",
                latest_changes="You have the latest version available.")
            Editor.ShowMessageBox(TITLE, message)
        return True
        
    if command == "RDBG_version_silent":
    
        version_checker = VersionChecker()
        debug_log("Checking local version.")
        version_checker.determine_installed_version()
        
        # scrape the forum to determine the latest version
        debug_log("Checking latest version.")
        version_checker.scrape_forum()
        
        debug_log("LatestVersion: {version}".format(version=version_checker.latest_version))
        debug_log("LocalVersion: {version}".format(version=version_checker.local_version))
        if version_checker.latest_version > version_checker.local_version:
            message = "{latest_changes}\n{separator}\n\nLocal Version: {local}\nLatest Version: {latest}\n\nRun 'RDBG_update_latest' command to update.".format(
                latest=".".join(version_checker.latest_version), 
                local=".".join(version_checker.local_version),
                separator="----------------------------------------------------------------------------",
                latest_changes=version_checker.forum_data[0]['post_content'])
            
            log(message)
            Editor.ShowMessageBox(TITLE, message)
        else:
            log("RemedyBG is up to date with latest version {VERSION}".format(VERSION=".".join(version_checker.latest_version)))
        return True
    
    if command == "RDBG_update_latest":
    
        version_checker = VersionChecker()
        log("Checking local version.")
        version_checker.determine_installed_version()
        
        # scrape the forum to determine the latest version
        log("Checking latest version.")
        version_checker.scrape_forum()
        
        debug_log("LatestVersion: {version}".format(version=version_checker.latest_version))
        debug_log("LocalVersion: {version}".format(version=version_checker.local_version))
        if version_checker.latest_version > version_checker.local_version:
            log("Attempting to download Version {latest}".format(latest=".".join(version_checker.latest_version)))
            
            version_checker.download_latest()
            
        else:
            message = "Local Version: {local}\nLatest Version: {latest}\n{separator}\n\n{latest_changes}".format(
                latest=".".join(version_checker.latest_version), 
                local=".".join(version_checker.local_version),
                separator="----------------------------------------------------------------------------",
                latest_changes="You have the latest version available.")
            Editor.ShowMessageBox(TITLE, message)
        return True
            
    
    return False

Editor.AddCommandPanelHandlerFunction(HandleCommandPanelCommand)


if Editor.GetSetting("RemedyBG_Updater.UpdateOnBoot") == "true":
    HandleCommandPanelCommand("RDBG_version_silent")
