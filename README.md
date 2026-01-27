# RSF-Stats-Sync
A simple tool to synchronize your **RallySimFans (RSF)** records with your local **Richard Burns Rally** database (RaceStat plugin).

If you reinstalled the RBR RSF plugin and forgot to make a backup, you can still recover your personal records from the RSF website. 
This script automates that process for you. Once restored, you will be able to see a comparison at the end of each stage, showing your old records if they are faster than your current ones.


## How to use
1. Go to Release and download .exe file or go to installation part if u dont want to use .exe file
2. **RBR Folder Path**: Select your main Richard Burns Rally installation folder.
3. **RSF User ID**: Enter your numeric User ID (see instructions below).
4. **PHPSESSID**: Enter your active session cookie (see instructions below).
5. **Start Sync**: Click the button and wait for the process to finish.
   
<img width="1054" height="1127" alt="image" src="https://github.com/user-attachments/assets/f9013730-b016-4e5a-8d1a-16e9fe8b8d75" />

---

## How to find your IDs

### 1. RSF User ID
* Log in to [rallysimfans.hu](https://www.rallysimfans.hu/).
* Go to **"Stats"** on your profile.
* ID is bellow your username on the table (example: **12345**)


### 2. PHPSESSID (Session ID)
This tool requires your session cookie to access your personal rank data.
* Open [rallysimfans.hu](https://www.rallysimfans.hu/) and log in.
* Press **F12** on your keyboard to open **Developer Tools**.
* Go to the **Application** tab (Chrome/Edge) or **Storage** tab (Firefox).
* In the left sidebar, expand **Cookies** and select `https://www.rallysimfans.hu`.
* Find the row named `PHPSESSID`.
* Copy the string of letters and numbers in the **Value** column.



---

## Installation

Ensure you have Python installed, then run the following commands in your terminal:

```bash
pip install -r requirements.txt
python FetchRSFRecords.py
