import sqlite3
import requests
from bs4 import BeautifulSoup
import json
import time
from datetime import datetime
import configparser
import os
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox

# === SYNC LOGIC ===

class RSFSyncLogic:
    def __init__(self, rbr_path, user_id, session_id, log_callback, progress_callback):
        self.rbr_path = rbr_path
        self.user_id = user_id
        self.session_id = session_id
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        
        # Local database path for RaceStat plugin
        self.db_path = os.path.join(rbr_path, 'Plugins', 'NGPCarMenu', 'RaceStat', 'raceStatDB.sqlite3')
        
        # Mapping of RSF website group IDs to readable car class names
        self.group_map = {
            "71": "Super 1600", "125": "Rally 2", "31": "Group B", "30": "Group A8", 
            "10": "WRC 1.6", "32": "Group N4", "21": "Group 2", "22": "Group 4", 
            "23": "Group A5", "78": "Group A6", "24": "Group A7", "33": "Group R1", 
            "34": "Group R2", "35": "Group R3", "36": "Group R4", "37": "Group R5", 
            "38": "Group RGT", "111": "Super 2000", "118": "Rally 5", "104": "Rally 4", "108": "Rally 3"
        }

    def log(self, message):
        self.log_callback(message)

    def validate_paths(self):
        """Checks if the required RBR directories and database exist."""
        if not os.path.exists(self.rbr_path):
            self.log("!!! ERROR: RBR folder not found.")
            return False
        if not os.path.exists(self.db_path):
            self.log("!!! ERROR: Database not found in Plugins.")
            return False
        return True

    def convert_time_to_seconds(self, time_str):
        """Converts RSF time format (M:S.ms) to total seconds."""
        try:
            if ':' in time_str:
                m, s = time_str.split(':')
                return int(m) * 60 + float(s.replace(',', '.'))
            return float(time_str.replace(',', '.'))
        except: return 0.0

    def process_page(self, html_content, curr, r_date, r_time):
        """Parses HTML from RSF stats page and inserts new records into SQLite."""
        if "usersstats.php" not in html_content and "Logged in as" not in html_content:
            return "AUTH_ERROR"
            
        soup = BeautifulSoup(html_content, 'html.parser')
        rows = soup.find_all('tr')
        if len(rows) < 2: return 0
        
        group_added = 0
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 8: continue
            
            s_name = cols[1].get_text(strip=True) # Stage Name
            t_str = cols[6].get_text(strip=True)  # Time String
            c_name = cols[5].get_text(strip=True)  # Car Name
            
            if not t_str or "Download" in s_name: continue
            
            f_time = self.convert_time_to_seconds(t_str)
            if f_time == 0: continue
            
            # Find matching Stage in local database
            curr.execute("SELECT MapKey FROM D_Map WHERE StageName = ?", (s_name,))
            m_res = curr.fetchone()
            if not m_res: continue
            
            # Find matching Car in local database
            curr.execute("SELECT CarKey FROM D_Car WHERE ModelName = ?", (c_name,))
            c_res = curr.fetchone()
            if not c_res: continue
            
            # Check if this specific result already exists (duplicates prevention)
            curr.execute("SELECT 1 FROM F_RallyResult WHERE MapKey=? AND CarKey=? AND ABS(FinishTime - ?) < 0.01", 
                         (m_res[0], c_res[0], f_time))
            
            if not curr.fetchone():
                curr.execute("""INSERT INTO F_RallyResult (RaceDate, RaceDateTime, CarKey, MapKey, FinishTime, Split1Time, Split2Time, ProfileName, PluginType, PluginSubType) 
                                VALUES (?, ?, ?, ?, ?, 0, 0, 'RSF_SYNC', 'RSF', 'SD')""", 
                             (r_date, r_time, c_res[0], m_res[0], f_time))
                group_added += 1
        return group_added

    def run(self):
        """Main loop that iterates through all car groups and fetches data."""
        if not self.validate_paths(): return 0
        total_added = 0
        try:
            conn = sqlite3.connect(self.db_path)
            curr = conn.cursor()
            now = datetime.now()
            r_d, r_t = int(now.strftime("%Y%m%d")), now.strftime("%H%M%S")
            
            headers = {
                'User-Agent': 'Mozilla/5.0', 
                'Cookie': f'PHPSESSID={self.session_id}', 
                'Referer': 'https://www.rallysimfans.hu/rbr/usersstats.php'
            }

            groups = list(self.group_map.items())
            for i, (g_id, g_name) in enumerate(groups):
                self.log(f"Fetching {g_name}...")
                url = f"https://www.rallysimfans.hu/rbr/usersstats.php?user_stats={self.user_id}&act=rank&cg={g_id}"
                
                try:
                    resp = requests.get(url, headers=headers, timeout=15)
                    res = self.process_page(resp.text, curr, r_d, r_t)
                    
                    if res == "AUTH_ERROR":
                        self.log("!!! ERROR: Session invalid (check PHPSESSID).")
                        break
                    
                    self.log(f"   -> Added {res} records.")
                    total_added += res
                except Exception as e:
                    self.log(f"   -> Network Error: {e}")
                
                # Update progress bar UI
                self.progress_callback((i + 1) / len(groups))
                time.sleep(0.5) # Anti-spam delay

            conn.commit()
            conn.close()
            return total_added
        except Exception as e:
            self.log(f"!!! DB Error: {e}")
            return 0

# === GUI APPLICATION ===

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("RSF Stats Sync Tool")
        self.geometry("700x720")
        ctk.set_appearance_mode("dark")
        
        # Load local configuration
        self.config = configparser.ConfigParser()
        self.config_file = 'config.ini'
        self.config.read(self.config_file)

        ctk.CTkLabel(self, text="RSF RBR Statistics Sync", font=("Arial", 22, "bold")).pack(pady=20)

        # Input fields
        self.path_entry = self.add_field("RBR Folder Path:", 'PATHS', 'rbr_path')
        ctk.CTkButton(self, text="Browse Folder", command=self.browse_folder).pack(pady=5)
        self.user_entry = self.add_field("RSF User ID:", 'RSF', 'user_id')
        self.session_entry = self.add_field("PHPSESSID (Cookie):", 'RSF', 'session_id')

        # Log display
        self.log_box = ctk.CTkTextbox(self, width=600, height=200)
        self.log_box.pack(pady=15)

        # Visual progress feedback
        self.progress_bar = ctk.CTkProgressBar(self, width=600)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=10)

        self.btn_sync = ctk.CTkButton(self, text="START SYNC", fg_color="#2ecc71", hover_color="#27ae60", 
                                      font=("Arial", 16, "bold"), height=45, command=self.start_thread)
        self.btn_sync.pack(pady=10)

    def add_field(self, label, section, key):
        """Helper to create labeled input fields that auto-save."""
        ctk.CTkLabel(self, text=label).pack()
        entry = ctk.CTkEntry(self, width=500)
        entry.pack(pady=2)
        entry.insert(0, self.config.get(section, key, fallback=''))
        entry.bind("<KeyRelease>", lambda e: self.save_all())
        return entry

    def save_all(self):
        """Saves current GUI inputs to config.ini file."""
        if not self.config.has_section('RSF'): self.config.add_section('RSF')
        if not self.config.has_section('PATHS'): self.config.add_section('PATHS')
        self.config.set('PATHS', 'rbr_path', self.path_entry.get())
        self.config.set('RSF', 'user_id', self.user_entry.get())
        self.config.set('RSF', 'session_id', self.session_entry.get())
        with open(self.config_file, 'w', encoding='utf-8') as f: self.config.write(f)

    def browse_folder(self):
        f = filedialog.askdirectory()
        if f:
            self.path_entry.delete(0, 'end')
            self.path_entry.insert(0, f)
            self.save_all()

    def start_thread(self):
        """Prevents GUI freezing by running the sync logic in a background thread."""
        self.btn_sync.configure(state="disabled", text="Syncing...")
        self.log_box.delete("1.0", "end")
        self.progress_bar.set(0)
        threading.Thread(target=self.do_sync, daemon=True).start()

    def do_sync(self):
        logic = RSFSyncLogic(self.path_entry.get(), self.user_entry.get(), 
                             self.session_entry.get(), self.add_log, self.update_progress)
        count = logic.run()
        self.after(0, lambda: self.finish_sync(count))

    def update_progress(self, val):
        self.after(0, lambda: self.progress_bar.set(val))

    def finish_sync(self, count):
        """Resets the UI and shows a final summary popup."""
        self.btn_sync.configure(state="normal", text="START SYNC")
        self.add_log(f"--- FINISHED. Total records: {count} ---")
        messagebox.showinfo("Done", f"Sync Complete!\nAdded {count} new records to your RBR database.")

    def add_log(self, text):
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")

if __name__ == "__main__":
    app = App()
    app.mainloop()