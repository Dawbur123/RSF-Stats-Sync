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
        
        # Paths to local RSF cache and database
        self.db_path = os.path.join(rbr_path, 'Plugins', 'NGPCarMenu', 'RaceStat', 'raceStatDB.sqlite3')
        self.cars_json_path = os.path.join(rbr_path,'rsfdata', 'cache', 'cars.json')
        self.car_model_json_path = os.path.join(rbr_path,'rsfdata', 'cache', 'carmodels.json')
        
        # FIA Groups mapping (add more IDs as needed)
        self.group_map = {
            "78": "Group A6"
        }

        # Load car data from cache
        self.cars_dict = {}
        if os.path.exists(self.cars_json_path):
            try:
                with open(self.cars_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for car in data:
                        self.cars_dict[car['name']] = car
                self.log(f"[*] Loaded {len(self.cars_dict)} cars from cars.json")
            except Exception as e:
                self.log(f"!!! Error loading cars JSON: {e}")

        # Load car model technical data from cache
        self.models_dict = {}
        if os.path.exists(self.car_model_json_path):
            try:
                with open(self.car_model_json_path, 'r', encoding='utf-8') as f:
                    m_data = json.load(f)
                    for model in m_data:
                        # Indexing by ID as string for reliable matching
                        self.models_dict[str(model['id'])] = model
                self.log(f"[*] Loaded {len(self.models_dict)} models from carmodels.json")
            except Exception as e:
                self.log(f"!!! Error loading carmodels JSON: {e}")

    def log(self, message):
        self.log_callback(message)

    def convert_time_to_seconds(self, time_str):
        try:
            if ':' in time_str:
                m, s = time_str.split(':')
                return int(m) * 60 + float(s.replace(',', '.'))
            return float(time_str.replace(',', '.'))
        except: return 0.0

    def process_page(self, html_content, curr, r_date, r_time, g_name):
        if "usersstats.php" not in html_content and "Logged in as" not in html_content:
            return "AUTH_ERROR"
            
        soup = BeautifulSoup(html_content, 'html.parser')
        rows = soup.find_all('tr')
        if len(rows) < 2: return 0
        
        group_added = 0
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 8: continue
            
            m_id_str = cols[0].get_text(strip=True) # Map ID
            s_name = cols[1].get_text(strip=True)   # Stage Name
            l_str = cols[2].get_text(strip=True)    # Length
            surf_str = cols[3].get_text(strip=True) # Surface
            
            t_str = cols[6].get_text(strip=True)    # Finish Time
            c_name = cols[5].get_text(strip=True)   # Car Name
            
            if not t_str or "Download" in s_name: continue
            
            f_time = self.convert_time_to_seconds(t_str)
            if f_time == 0: continue

            # --- MAP DATA PARSING ---
            m_id = int(m_id_str) if m_id_str.isdigit() else 0
            try:
                length_m = int(float(l_str.split(' ')[0].replace(',', '.')) * 1000)
            except:
                length_m = 0
            surface_char = surf_str[0].upper() if surf_str else 'G'
            
            # --- D_Map Logic ---
            curr.execute("SELECT MapKey FROM D_Map WHERE StageName = ?", (s_name,))
            m_res = curr.fetchone()
            if not m_res:
                self.log(f"   [!] New Map: {s_name} (ID: {m_id})")
                curr.execute("""
                    INSERT INTO D_Map (MapID, StageName, Surface, Length, Format, RBRInstallType)  
                    VALUES (?, ?, ?, ?, 'RBR', 'RSF')
                """, (m_id, s_name, surface_char, length_m))
                map_key = curr.lastrowid
            else:
                map_key = m_res[0]
                curr.execute("""
                    UPDATE D_Map SET MapID = ?, Surface = ?, Length = ? 
                    WHERE MapKey = ? AND (MapID = 0 OR MapID IS NULL)
                """, (m_id, surface_char, length_m, map_key))

            # --- D_Car Logic ---
            curr.execute("SELECT CarKey FROM D_Car WHERE ModelName = ?", (c_name,))
            c_res = curr.fetchone()
            
            if not c_res:
                car_info = self.cars_dict.get(c_name, {})
                c_id = car_info.get('id', 999)
                phys = car_info.get('path', 'UNK')
                
                # Match folder path from carmodels.json
                cm_id = str(car_info.get('carmodel_id', ''))
                model_info = self.models_dict.get(cm_id, {})
                path_from_json = model_info.get('path', c_name.split(' ')[0])
                fold = f"Cars\\{path_from_json}"
                
                raw_rev = car_info.get('rev', '1')
                full_rev = f"revision {raw_rev}"

                self.log(f"   [+] New Car: {c_name} (ID: {c_id})")
                curr.execute("""
                    INSERT INTO D_Car (CarID, ModelName, FIACategory, Physics, Folder, Revision, NGPVersion)  
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (c_id, c_name, g_name, phys, fold, full_rev, '75779508'))
                car_key = curr.lastrowid
            else:
                car_key = c_res[0]
            
            # --- F_RallyResult Logic ---
            curr.execute("SELECT 1 FROM F_RallyResult WHERE MapKey=? AND CarKey=? AND ABS(FinishTime - ?) < 0.01", 
                         (map_key, car_key, f_time))
            if not curr.fetchone():
                curr.execute("""
                    INSERT INTO F_RallyResult (
                        RaceDate, RaceDateTime, CarKey, MapKey, 
                        Split1Time, Split2Time, FinishTime, 
                        FalseStartPenaltyTime, CutPenaltyTime, OtherPenaltyTime, 
                        FalseStart, CallForHelp, TransmissionType, TyreType, TyreSubType, 
                        DamageType, TimeOfDay, WeatherType, SkyCloudType, SkyType, 
                        SurfaceWetness, SurfaceAge, ProfileName, PluginType, PluginSubType, CarSlot
                    ) 
                    VALUES (?, ?, ?, ?, 0, 0, ?, 0, 0, 0, 0, 0, 'M', 'G', 'D', 0, 0, 'S', 0, 0, 0, 0, 'MULLIGATAWNY', 'RSF', 'SD', 0)
                """, (r_date, r_time, car_key, map_key, f_time))
                group_added += 1

        return group_added

    def run(self):
        if not os.path.exists(self.db_path):
            self.log("!!! ERROR: RBR Database not found.")
            return 0
        
        total_added = 0
        try:
            conn = sqlite3.connect(self.db_path)
            curr = conn.cursor()
            now = datetime.now()
            r_d, r_t = int(now.strftime("%Y%m%d")), now.strftime("%H%M%S")
            headers = {'User-Agent': 'Mozilla/5.0', 'Cookie': f'PHPSESSID={self.session_id}'}

            groups = list(self.group_map.items())
            for i, (g_id, g_name) in enumerate(groups):
                self.log(f"Fetching class: {g_name}...")
                url = f"https://www.rallysimfans.hu/rbr/usersstats.php?user_stats={self.user_id}&act=rank&cg={g_id}"
                try:
                    resp = requests.get(url, headers=headers, timeout=15)
                    res = self.process_page(resp.text, curr, r_d, r_t, g_name)
                    if res == "AUTH_ERROR":
                        self.log("!!! ERROR: Session expired.")
                        break
                    if isinstance(res, int) and res > 0:
                        self.log(f"   -> Added {res} results.")
                        total_added += res
                except Exception as e:
                    self.log(f"   -> Network Error: {e}")
                
                self.progress_callback((i + 1) / len(groups))
                time.sleep(0.4)

            conn.commit()
            conn.close()
            return total_added
        except Exception as e:
            self.log(f"!!! Database Error: {e}")
            return 0

# === GUI APPLICATION ===

class App(ctk.CTk):
    def __init__(self):
        # Prevent initial flickering/scaling jumps
        ctk.set_widget_scaling(1.0)
        super().__init__()
        self.title("RSF Stats Sync Tool")
        ctk.set_appearance_mode("dark")
        
        # Initialize config handler
        self.config = configparser.ConfigParser()
        self.config_file = 'config.ini'
        self.config.read(self.config_file)

        # Set geometry from saved config or use default
        self.geometry(self.config.get('GUI', 'geometry', fallback='600x780+100+100'))

        ctk.CTkLabel(self, text="RSF RBR Statistics Sync", font=("Arial", 24, "bold")).pack(pady=20)

        self.path_entry = self.add_field("RBR Folder Path:", 'PATHS', 'rbr_path')
        ctk.CTkButton(self, text="Browse Folder", command=self.browse_folder).pack(pady=5)
        self.user_entry = self.add_field("RSF User ID:", 'RSF', 'user_id')
        self.session_entry = self.add_field("PHPSESSID:", 'RSF', 'session_id')

        self.log_box = ctk.CTkTextbox(self, width=620, height=280)
        self.log_box.pack(pady=15)
        self.progress_bar = ctk.CTkProgressBar(self, width=620)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=10)

        self.btn_sync = ctk.CTkButton(self, text="SYNC NOW", fg_color="#2ecc71", hover_color="#27ae60", 
                                      font=("Arial", 16, "bold"), height=50, command=self.start_thread)
        self.btn_sync.pack(pady=15)

    def add_field(self, label, section, key):
        ctk.CTkLabel(self, text=label).pack()
        entry = ctk.CTkEntry(self, width=550)
        entry.pack(pady=2)
        entry.insert(0, self.config.get(section, key, fallback=''))
        entry.bind("<KeyRelease>", lambda e: self.save_all())
        return entry

    def save_all(self):
        """Save settings and current window geometry to config.ini"""
        if not self.config.has_section('RSF'): self.config.add_section('RSF')
        if not self.config.has_section('PATHS'): self.config.add_section('PATHS')
        if not self.config.has_section('GUI'): self.config.add_section('GUI')
        
        self.config.set('GUI', 'geometry', self.geometry())
        self.config.set('PATHS', 'rbr_path', self.path_entry.get())
        self.config.set('RSF', 'user_id', self.user_entry.get())
        self.config.set('RSF', 'session_id', self.session_entry.get())
        
        with open(self.config_file, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def browse_folder(self):
        f = filedialog.askdirectory()
        if f:
            self.path_entry.delete(0, 'end')
            self.path_entry.insert(0, f)
            self.save_all()

    def start_thread(self):
        self.btn_sync.configure(state="disabled", text="Syncing...")
        self.log_box.delete("1.0", "end")
        threading.Thread(target=self.do_sync, daemon=True).start()

    def do_sync(self):
        logic = RSFSyncLogic(self.path_entry.get(), self.user_entry.get(), 
                             self.session_entry.get(), self.add_log, self.update_progress)
        count = logic.run()
        self.after(0, lambda: self.finish_sync(count))

    def update_progress(self, val):
        self.after(0, lambda: self.progress_bar.set(val))

    def finish_sync(self, count):
        self.btn_sync.configure(state="normal", text="SYNC NOW")
        messagebox.showinfo("Done", f"Sync completed!\nAdded {count} new results.")

    def add_log(self, text):
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")

if __name__ == "__main__":
    app = App()
    app.mainloop()