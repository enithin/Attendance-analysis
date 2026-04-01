import streamlit as st
import pandas as pd
import re

# --- 1. SETTINGS ---
SHIFTS = {
    'Female':  {'start': 570, 'end': 1140}, 
    'Special': {'start': 570, 'end': 1110}, 
    'Male':    {'start': 600, 'end': 1200}, 
    'Sunday':  {'start': 600, 'end': 1020}  
}
LUNCH_START, LUNCH_END = 750, 930 
LUNCH_LIMIT, TEA_LIMIT = 60, 15

def format_duration(m):
    return f"{int(m//60)}h {int(m%60)}m" if m > 0 else "0m"

# --- 2. ANALYSIS ENGINE ---
def analyze_day_full(punch_str, shift_cat, is_sunday, is_holiday):
    res = {'Status': 'Skipped', 'Work_Mins': 0, 'Lunch_Mins': 0, 'Tea_Mins': 0,
           'Late_In': 0, 'Early_In': 0, 'Late_Out': 0, 'Early_Out': 0, 'Audit': ''}
    
    if pd.isna(punch_str) or str(punch_str).strip() == "":
        if is_sunday or is_holiday: return res
        res['Status'] = '🔴 LEAVE'
        return res

    times = sorted(list(set(re.findall(r'(\d{2}:\d{2})', str(punch_str)))))
    if len(times) < 2:
        res['Status'] = '⚠️ Partial Punch'
        return res

    t_mins = [int(t.split(':')[0])*60 + int(t.split(':')[1]) for t in times]
    s_cfg = SHIFTS['Sunday'] if is_sunday else SHIFTS.get(str(shift_cat).strip(), SHIFTS['Special'])
    
    res['Late_In'] = max(0, t_mins[0] - s_cfg['start'])
    res['Early_In'] = max(0, s_cfg['start'] - t_mins[0])
    res['Late_Out'] = max(0, t_mins[-1] - s_cfg['end'])
    res['Early_Out'] = max(0, s_cfg['end'] - t_mins[-1])

    cleaned = [t_mins[0]]
    for t in t_mins[1:]:
        if t - cleaned[-1] >= 2: cleaned.append(t)
            
    logs = []
    if res['Late_In'] > 5: logs.append(f"Late({res['Late_In']}m)")
    if res['Early_Out'] > 5: logs.append(f"Early-Exit({res['Early_Out']}m)")

    for i in range(0, len(cleaned), 2):
        if i+1 < len(cleaned): res['Work_Mins'] += (cleaned[i+1] - cleaned[i])
        if i + 2 < len(cleaned):
            gap_start, gap_dur = cleaned[i+1], (cleaned[i+2] - cleaned[i+1])
            if LUNCH_START <= gap_start <= LUNCH_END:
                res['Lunch_Mins'] += gap_dur
                if gap_dur > LUNCH_LIMIT: logs.append(f"Long Lunch")
            else:
                res['Tea_Mins'] += gap_dur
                if gap_dur > TEA_LIMIT: logs.append(f"Long Tea")

    res['Status'] = "✅ Present" if not is_sunday else "⭐ Sunday Work"
    res['Audit'] = ", ".join(logs)
    return res

# --- 3. MAIN UI ---
st.set_page_config(layout="wide")
st.title("🛡️ Staff Attendance & Punctuality Auditor")

with st.sidebar:
    st.header("📂 Upload Files")
    att_f = st.file_uploader("1. Attendance Logs", type="csv")
    staff_f = st.file_uploader("2. Staff Master", type="csv")
    h_f = st.file_uploader("3. Holiday List", type="csv")

if att_f and staff_f and h_f:
    df_att = pd.read_csv(att_f, sep=None, engine='python')
    df_staff = pd.read_csv(staff_f, sep=None, engine='python')
    df_h = pd.read_csv(h_f, sep=None, engine='python')

    # Column Detection
    def find_col(df, keys):
        for k in keys:
            for c in df.columns:
                if k.lower().replace(" ", "") in c.lower().replace(" ", ""): return c
        return None

    id_col = find_col(df_staff, ['code', 'id'])
    name_col = find_col(df_staff, ['name', 'employee'])
    shift_col = find_col(df_staff, ['shift', 'category'])
    h_date_col = find_col(df_h, ['date', 'holiday'])

    # Processing
    df_att['AttendanceDate'] = pd.to_datetime(df_att['AttendanceDate']).dt.date
    df_h[h_date_col] = pd.to_datetime(df_h[h_date_col]).dt.date
    holiday_map = {row[h_date_col]: str(row.get('Type', 'Common')).lower() for _, row in df_h.iterrows()}

    staff_clean = df_staff[[id_col, name_col, shift_col]].copy()
    staff_clean.columns = ['ID', 'Name', 'Shift']
    
    df = pd.merge(df_att, staff_clean, left_on='Employee Code', right_on='ID', how='left')
    df['IsHoliday'] = df['AttendanceDate'].isin(holiday_map)
    df['IsSunday'] = pd.to_datetime(df['AttendanceDate']).dt.dayofweek == 6

    # Critical Step: Analysis
    results = df.apply(lambda r: analyze_day_full(r['PunchRecords'], r['Shift'], r['IsSunday'], r['IsHoliday']), axis=1).tolist()
    report = pd.concat([df.reset_index(drop=True), pd.DataFrame(results)], axis=1)
    report = report[report['Status'] != 'Skipped']

    # --- SIDEBAR FILTER ---
    st.sidebar.divider()
    clean_names = sorted([str(x).strip() for x in report['Name'].unique() if pd.notna(x)])
    sel_staff = st.sidebar.selectbox("🔍 Select Employee", ["All Staff"] + clean_names)
    
    if sel_staff != "All Staff":
        report = report[report['Name'].astype(str) == sel_staff]

    # --- TABS DEFINITION (THIS WAS THE MISSING PART) ---
    tab1, tab2 = st.tabs(["📅 Daily Detail Audit", "💰 Payroll Summary"])
    
    with tab1:
        st.subheader(f"Showing Details for: {sel_staff}")
        view_df = report.copy()
        # Formatting durations for readability
        for c in ['Early_In', 'Late_In', 'Early_Out', 'Late_Out']:
            view_df[c] = view_df[c].apply(lambda x: f"{x}m" if x > 0 else "-")
        
        disp = ['Name', 'AttendanceDate', 'Status', 'Early_In', 'Late_In', 'Early_Out', 'Late_Out', 'Audit']
        st.dataframe(view_df[disp], use_container_width=True)

    with tab2:
        st.subheader("Monthly Totals")
        summary = report.groupby(['ID', 'Name']).agg({
            'Status': lambda x: (x == '🔴 LEAVE').sum(),
            'Work_Mins': 'sum', 'IsSunday': 'sum'
        }).reset_index()
        
        summary['Payable Days'] = (len(report['AttendanceDate'].unique()) - summary['Status']) + summary['IsSunday']
        summary.columns = ['ID', 'Name', 'Leaves', 'Total Delay', 'Sunday', 'Payable Days']
        st.dataframe(summary, use_container_width=True)
