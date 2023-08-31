
# RemedyBG debugger integration
RemedyBG: https://remedybg.handmade.network/  

For more info/documentation **please read the top of the python script.**
Note that this script only works with RemedyBG version 0.3.8 and above

To install the script copy it to %appdata%\10x\PythonScripts\

# RemedyBG Debugger Updater 
Version: 0.1.0

**Note that you don't need the updater to use the debugger, the steps below are optional**

Requires the following python modules to be installed:
- requests
- BeautifulSoup4
        
To install these modules in 10x's python use the pip command with python3 and set  
the target to be 10x's installation directory:

> python3 -m pip install --target="C:\Program Files\PureDevSoftware\10x\Lib\site-packages"
> requests

> python3 -m pip install --target="C:\Program Files\PureDevSoftware\10x\Lib\site-packages"
> BeautifulSoup4

**You can get the Portal Token from the itch.io download page url for RemedyBG:**  
- in any browser login to itch.io
- navigate to https://remedybg.itch.io/remedybg
- if you havnt purchased RemedyBG, do so now.  Support the dev!
- click the "Download" button
- The PortalToken value will be in the url for the downloads page
    e.g: https://remedybg.itch.io/remedybg/download/{PortalToken}
    
    

**You can get the Itch.io Login Cookie and Token by reading the saved cookies via your browser:**
- in chrome login to itch.io
- press f12 and go to the "application" tab
- under "storage" expand "Cookies"
- use the "itchio" value for RemedyBG_Updater.ItchLoginCookie
- use the "itchio_token" value for RemedyBG_Updater.ItchLoginToken
