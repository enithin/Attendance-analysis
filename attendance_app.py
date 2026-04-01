import streamlit as st
import pandas as pd
import re
from datetime import datetime

# --- CONFIGURATION: SHIFT DEFINITIONS (Minutes from Midnight) ---
SHIFTS = {
    'Female':  {'start': 570, 'end': 1140}, # 09:30 AM - 07:00 PM
    'Special': {'start': 570, 'end': 1110}, # 09:30 AM - 06:30 PM
    'Male':    {'start': 600, 'end': 1200}, # 10:00 AM - 08:00 PM
    'Sunday':  {'start': 600, 'end': 1020}  # 10:00 AM - 05:00 PM
}

LUNCH_START = 750 # 12:30 PM
LUNCH_END = 930   # 03:30 PM
LUNCH_LIMIT = 60
TEA_LIMIT = 15

def format_min_to_hm(minutes):
    if pd.isna(minutes) or minutes == 0: return "0m"
    return f"{int(minutes//60)}h {int(minutes%60)}m"

def analyze_day(punch_str, shift_cat, is_sunday, is_holiday):
    # Initialize default result to prevent NoneType errors
    res = {
        'Status': 'Skipped', 'Work_Mins': 0, 'Lunch_Mins': 0, 'Tea_Mins': 0,
        'Late_In': 0, 'Early_In': 0, 'Late_Out': 0, 'Early_Out': 0, 'Audit': ''
    }
    
    # 1. Handle Leaves vs Holidays
    if pd.isna(punch_str) or str(punch_str).strip() == "":
        if is_sunday or is_holiday: return res
        res['Status'] = '🔴 LEAVE'
        return res

    # 2. Parse Punches
    times = sorted(list(set(re.findall(r'(\d{2}:\d{2})', str(punch_str)))))
    if len(times) < 2:
        res['Status'] = '⚠️ Partial Punch'
        return res

    t_mins = [int(t.split(':')[0])*60 + int(t.split(':')[1]) for t in times]
    s_cfg = SHIFTS['Sunday'] if is_sunday else SHIFTS.get(str(shift_cat).strip(), SHIFTS['Special'])
    
    # 3. Punctuality
    res['Late_In'] = max(0, t_mins[0] - s_cfg['start'])
    res['Early_In'] = max(0, s_cfg['start'] - t_mins[0])
    res['Late_Out'] = max(0, t_mins[-1] - s_cfg['end'])
    res['Early_Out'] = max(0, s_cfg['end'] - t_mins[-1])

    # 4. Work & Break Analysis (Gap Analysis)
    cleaned = [t_mins[0]]
    for t in t_mins[1:]:
        if t - cleaned[-1] >= 2: cleaned.append(t)
            
    audit_logs = []
    if res['Late_In'] > 5: audit_logs.append(f"Late In({res['Late_In']}m)")
    if res['Early_Out'] > 5: audit_logs.append(f"Early Out({res['Early_Out']}m)")

    for i in range(0, len(cleaned), 2):
        if i+1 < len(cleaned): res['Work_Mins'] += (cleaned[i+1] - cleaned[i])
        if i + 2 < len(cleaned):
            gap_start = cleaned[i+1]
            gap_dur = cleaned[i+2] - cleaned[i+1]
            if LUNCH_START <= gap_start <= LUNCH_END:
                res['Lunch_Mins'] += gap_dur
                if gap_dur > LUNCH_LIMIT: audit_logs.append(f"Long Lunch({gap_dur}m)")
            else:
                res['Tea_Mins'] += gap_dur
                if gap_dur > TEA_LIMIT: audit_logs.append(f"Long Tea({gap_dur}m)")

    res['Status'] = "✅ Present" if not is_sunday else "⭐ Sunday Work"
    res['Audit'] = ", ".join(audit_logs)
    return res

# --- STREAMLIT UI ---
st.set_page_config(layout="wide", page_title="Ultimate Attendance Auditor")
st.title("🛡️ Ultimate Attendance & Punctuality Auditor")

with st.sidebar:
    st.header("📂 Data Upload Center")
    att_file = st.file_uploader("1. Attendance Logs", type="csv")
    staff_file = st.file_uploader("2. Staff Master", type="csv")
    h_file = st.file_uploader("3. Holiday List", type="csv")

if att_file and staff_file and h_file:
    # Load with auto-delimiter detection
    df_att = pd.read_csv(att_file, sep=None, engine='python')
    df_staff = pd.read_csv(staff_file, sep=None, engine='python')
    df_h = pd.read_csv(h_file, sep=None, engine='python')

    # Helper for robust column mapping
    def find_col(df, keywords):
        for k in keywords:
            for c in df.columns:
                if k.lower().replace(" ", "") in c.lower().replace(" ", ""): return c
        return None

    id_col = find_col(df_staff, ['code', 'id', 'emp'])
    name_col = find_col(df_staff, ['name', 'employee'])
    shift_col = find_col(df_staff, ['shift', 'category'])
    rel_col = find_col(df_staff, ['religion', 'faith'])
    h_date_col = find_col(df_h, ['date', 'holiday'])

    if not all([id_col, shift_col, name_col]):
        st.error("Column detection failed. Please ensure CSVs have ID, Name, and Shift Category.")
    else:
        # Pre-processing
        df_att['AttendanceDate'] = pd.to_datetime(df_att['AttendanceDate']).dt.date
        h_dates = pd.to_datetime(df_h[h_date_col]).dt.date.tolist()
        
        # Merge staff data
        staff_data = df_staff[[id_col, name_col, shift_col, rel_col]].copy()
        staff_data.columns = ['ID', 'Name', 'Shift', 'Religion']
        
        df = pd.merge(df_att, staff_data, left_on='Employee Code', right_on='ID', how='left')
        df['IsHoliday'] = df.apply(lambda r: r['AttendanceDate'] in h_dates and 
                                 (str(df_h.loc[df_h[h_date_col].dt.date == r['AttendanceDate'], 'Type'].values[0]).lower() == 'common' or 
                                  str(df_h.loc[df_h[h_date_col].dt.date == r['AttendanceDate'], 'Religion'].values[0]).lower() == str(r['Religion']).lower()), axis=1)
        df['IsSunday'] = pd.to_datetime(df['AttendanceDate']).dt.dayofweek == 6

        # Analysis
        results = df.apply(lambda r: analyze_day(r['PunchRecords'], r['Shift'], r['IsSunday'], r['IsHoliday']), axis=1).tolist()
        report = pd.concat([df.reset_index(drop=True), pd.DataFrame(results)], axis=1)
        report = report[report['Status'] != 'Skipped']

        # --- FILTERS ---
        st.sidebar.divider()
        sel_staff = st.sidebar.selectbox("🔍 Filter Staff", ["All Staff"] + sorted(report['Name'].unique().tolist()))
        if sel_staff != "All Staff": report = report[report['Name'] == sel_staff]

        tab1, tab2 = st.tabs(["📅 Daily Break & Punctuality Audit", "💰 Payroll Summary"])

        with tab1:
            view_cols = ['Name', 'AttendanceDate', 'Status', 'Late_In', 'Early_Out', 'Lunch_Mins', 'Tea_Mins', 'Audit']
            st.dataframe(report[view_cols], use_container_width=True)
            st.download_button("Export Daily Detail", report.to_csv(index=False), "daily_audit.csv")

        with tab2:
            summary = report.groupby(['ID', 'Name']).agg({
                'Status': lambda x: (x == '🔴 LEAVE').sum(),
                'Work_Mins': 'sum',
                'Lunch_Mins': 'sum',
                'Tea_Mins': 'sum',
                'IsSunday': 'sum'
            }).reset_index()
            
            summary['Payable Days'] = (len(report['AttendanceDate'].unique()) - summary['Status']) + summary['IsSunday']
            summary['Total Work'] = summary['Work_Mins'].apply(format_min_to_hm)
            
            final_summary = summary[['ID', 'Name', 'Status', 'IsSunday', 'Payable Days', 'Total Work', 'Lunch_Mins', 'Tea_Mins']]
            final_summary.columns = ['Emp ID', 'Staff Name', 'Leaves', 'Sundays worked', 'Payable Days', 'Total Work Time', 'Lunch(m)', 'Tea(m)']
            st.dataframe(final_summary, use_container_width=True)
            st.download_button("Export Payroll Summary", final_summary.to_csv(index=False), "payroll_summary.csv")
