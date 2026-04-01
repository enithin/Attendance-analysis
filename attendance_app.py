import streamlit as st
import pandas as pd
import re
from datetime import datetime

# --- 1. CONFIGURATION & HR POLICIES ---
SHIFTS = {
    'Female':  {'start': 570, 'end': 1140}, 
    'Special': {'start': 570, 'end': 1110}, 
    'Male':    {'start': 600, 'end': 1200}, 
    'Sunday':  {'start': 600, 'end': 1020}  
}

LUNCH_START, LUNCH_END = 750, 930
LUNCH_LIMIT, TEA_LIMIT = 60, 15
HALF_DAY_THRESHOLD, FULL_DAY_MINIMUM = 210, 360 

def find_c(df, keys):
    for k in keys:
        for c in df.columns:
            if k.lower() in str(c).lower().replace("_", "").replace(" ", ""): return c
    return None

# --- 2. THE STABLE CALCULATION ENGINE ---
def analyze_day_full(punch_str, shift_cat, is_sunday, is_holiday, h_type):
    res = {
        'Status': '🔴 LEAVE', 'Work_Mins': 0, 'Lunch_Mins': 0, 'Tea_Mins': 0,
        'Late_In': 0, 'Early_In': 0, 'Late_Out': 0, 'Early_Out': 0, 
        'Audit': '', 'Day_Value': 0.0, 'Holiday_Work_Bonus': 0,
        'Sunday_Worked': 0  # <--- FIXED: Explicitly tracking actual worked Sundays
    }
    
    val = str(punch_str).strip().lower()
    if pd.isna(punch_str) or val in ["", "nan", "0", "none"]:
        if is_sunday:
            res['Status'] = '🏠 Sunday Off'
        elif is_holiday:
            res['Status'] = f'🌴 Holiday Off ({str(h_type).title()})'
        return res

    matches = re.findall(r'(\d{1,2}:\d{2}(?::\d{2})?\s?(?:am|pm)?)', val)
    if not matches:
        res['Status'] = '⚠️ Format Error'
        return res

    t_mins = []
    for t in matches:
        for fmt in ('%H:%M', '%I:%M %p', '%H:%M:%S', '%I:%M:%S %p'):
            try:
                dt = datetime.strptime(t.upper(), fmt)
                t_mins.append(dt.hour * 60 + dt.minute)
                break
            except: continue
    
    t_mins = sorted(list(set(t_mins)))
    if len(t_mins) < 2:
        res['Status'] = '⚠️ Single Punch'
        return res

    s_cfg = SHIFTS['Sunday'] if is_sunday else SHIFTS.get(str(shift_cat).strip(), SHIFTS['Special'])
    res['Late_In'], res['Early_In'] = max(0, t_mins[0]-s_cfg['start']), max(0, s_cfg['start']-t_mins[0])
    res['Late_Out'], res['Early_Out'] = max(0, t_mins[-1]-s_cfg['end']), max(0, s_cfg['end']-t_mins[-1])

    logs = []
    if res['Late_In'] > 5: logs.append(f"Late({res['Late_In']}m)")
    if res['Early_Out'] > 5: logs.append(f"Early-Exit({res['Early_Out']}m)")
    
    cleaned = [t_mins[0]]
    for t in t_mins[1:]:
        if t - cleaned[-1] >= 2: cleaned.append(t)
        
    for i in range(0, len(cleaned), 2):
        if i+1 < len(cleaned): 
            res['Work_Mins'] += (cleaned[i+1] - cleaned[i])

    for i in range(1, len(cleaned)-1, 2):
        gap = cleaned[i+1] - cleaned[i]
        gap_start = cleaned[i]
        
        if LUNCH_START <= gap_start <= LUNCH_END:
            res['Lunch_Mins'] += gap
            if gap > LUNCH_LIMIT: logs.append(f"Long Lunch({gap}m)")
        else:
            res['Tea_Mins'] += gap
            if gap > TEA_LIMIT: logs.append(f"Long Tea({gap}m)")

    if is_holiday and str(h_type).lower() == 'common' and res['Work_Mins'] >= HALF_DAY_THRESHOLD:
        res['Holiday_Work_Bonus'] = 1

    # --- FIXED: Only credit Sunday_Worked if they actually worked ---
    if is_sunday and res['Work_Mins'] >= HALF_DAY_THRESHOLD: 
        res['Status'], res['Day_Value'] = "⭐ Sunday Work", 1.0
        res['Sunday_Worked'] = 1
    elif res['Work_Mins'] >= FULL_DAY_MINIMUM: 
        res['Status'], res['Day_Value'] = "✅ Present", 1.0
    elif res['Work_Mins'] >= HALF_DAY_THRESHOLD: 
        res['Status'], res['Day_Value'] = "🕒 Half Day", 0.5
    else: 
        res['Status'], res['Day_Value'] = "🔴 LEAVE (Short)", 0.0

    res['Audit'] = ", ".join(logs)
    return res

# --- 3. UI & AUTOMATIC DATA HANDSHAKE ---
st.set_page_config(layout="wide", page_title="HR Payroll Pro")
st.sidebar.markdown("<h1 style='text-align: center; color: #FF4B4B;'>HR ADMIN HUB</h1>", unsafe_allow_html=True)

with st.sidebar:
    st.header("📂 Data Upload Center")
    att_f = st.file_uploader("1. Attendance Logs", type="csv")
    staff_f = st.file_uploader("2. Staff Master", type="csv")
    h_f = st.file_uploader("3. Holiday List", type="csv")
    sal_f = st.file_uploader("4. Salary Master", type="csv")

if att_f and staff_f and h_f and sal_f:
    df_att = pd.read_csv(att_f, sep=None, engine='python')
    df_staff = pd.read_csv(staff_f, sep=None, engine='python')
    df_h = pd.read_csv(h_f, sep=None, engine='python')
    df_sal = pd.read_csv(sal_f, sep=None, engine='python')

    att_id_c = find_c(df_att, ['code', 'id', 'emp'])
    att_date_c = find_c(df_att, ['date', 'day'])
    att_punch_c = find_c(df_att, ['punch', 'record', 'logs'])
    
    staff_id_c = find_c(df_staff, ['code', 'id', 'emp'])
    staff_name_c = find_c(df_staff, ['name', 'employee'])
    staff_shift_c = find_c(df_staff, ['shift', 'cat'])
    staff_rel_c = find_c(df_staff, ['religion'])

    sal_id_c = find_c(df_sal, ['code', 'id', 'emp'])
    sal_base_c = find_c(df_sal, ['base', 'salary', 'pay'])

    if not all([att_id_c, att_punch_c, staff_id_c, staff_name_c]):
        st.error("❌ Column Mismatch. Ensure headers exist for 'Code/ID', 'Name', and 'Punches'.")
    else:
        df_att[att_id_c] = df_att[att_id_c].astype(str).str.strip()
        df_staff[staff_id_c] = df_staff[staff_id_c].astype(str).str.strip()
        df_att['AttendanceDate'] = pd.to_datetime(df_att[att_date_c]).dt.date
        
        overlap = [c for c in df_staff.columns if c in df_att.columns and c != att_id_c]
        df_att_clean = df_att.drop(columns=overlap)

        h_date_c = find_c(df_h, ['date', 'holiday'])
        h_type_c = find_c(df_h, ['type', 'category'])
        h_rel_c = find_c(df_h, ['religion', 'faith'])
        
        df_h[h_date_c] = pd.to_datetime(df_h[h_date_c]).dt.date
        
        def build_h_map(row):
            t = str(row[h_type_c]).strip().lower() if h_type_c else 'common'
            rel = str(row[h_rel_c]).strip().lower() if h_rel_c else 'none'
            return t, rel

        h_map = {row[h_date_c]: build_h_map(row) for _, row in df_h.iterrows()}

        report_raw = pd.merge(df_att_clean, df_staff, left_on=att_id_c, right_on=staff_id_c, how='left')
        report_raw[staff_name_c] = report_raw[staff_name_c].fillna("Unknown Staff")
        
        def get_h_info(r):
            d = r['AttendanceDate']
            if d in h_map:
                t, rel = h_map[d]
                emp_rel = str(r.get(staff_rel_c, 'None')).strip().lower() if staff_rel_c else 'none'
                if t == 'common' or rel == emp_rel:
                    return True, t
            return False, None

        report_raw[['IsHoliday', 'H_Type']] = report_raw.apply(lambda r: pd.Series(get_h_info(r)), axis=1)
        report_raw['IsSunday'] = pd.to_datetime(report_raw['AttendanceDate']).dt.dayofweek == 6

        results = report_raw.apply(lambda r: analyze_day_full(r[att_punch_c], r.get(staff_shift_c, 'Special'), r['IsSunday'], r['IsHoliday'], r['H_Type']), axis=1).tolist()
        report = pd.concat([report_raw.reset_index(drop=True), pd.DataFrame(results)], axis=1)
        report = report[report['Status'] != 'Skipped']

        # --- 4. HR POLICY ENGINE (NORMALIZED) ---
        summary = report.groupby([staff_id_c, staff_name_c]).agg({
            'Day_Value': 'sum', 
            'Status': lambda x: x.astype(str).str.contains('🔴 LEAVE').sum(), # Safe leave counter
            'Sunday_Worked': 'sum', # <--- FIXED: Now aggregates actual worked Sundays, NOT calendar Sundays
            'Holiday_Work_Bonus': 'sum'
        }).reset_index()

        def hr_policy(row):
            total_leaves = row['Status']
            sundays_worked = row['Sunday_Worked'] 
            
            net_leaves = max(0, total_leaves - sundays_worked)
            encashment = 2 if total_leaves == 0 else 0
            
            if net_leaves > 4: 
                deduction = total_leaves 
                note = f"Penalty Triggered (>4 Net Leaves)"
            elif net_leaves > 2: 
                deduction = net_leaves - 2 
                note = f"2 Paid, {deduction} Unpaid"
            else: 
                deduction = 0 
                note = "Within 2 Paid Limit"
            
            period_days = len(report['AttendanceDate'].unique())
            final_payable = (period_days - deduction) + row['Holiday_Work_Bonus'] + encashment
            return pd.Series([encashment, deduction, final_payable, net_leaves, note])

        summary[['Encashment_Bonus', 'Deduction', 'Final_Payable', 'Net_Leaves', 'Policy_Note']] = summary.apply(hr_policy, axis=1)

        # --- 5. TABS & VISUALS ---
        clean_names = sorted([str(x).strip() for x in report[staff_name_c].unique() if pd.notna(x) and x != "Unknown Staff"])
        sel_staff = st.sidebar.selectbox("🔍 Select Employee", ["All Staff"] + clean_names)

        tab1, tab2, tab3 = st.tabs(["📅 Daily Audit", "💰 Monthly Summary", "📄 Salary Slip"])

        with tab1:
            disp = report if sel_staff == "All Staff" else report[report[staff_name_c] == sel_staff]
            view_df = disp[[staff_name_c, 'AttendanceDate', 'Status', 'Work_Mins', 'Early_In', 'Late_In', 'Early_Out', 'Late_Out', 'Audit']].copy()
            view_df.columns = ['Name', 'Date', 'Status', 'Work (Mins)', 'Early In (m)', 'Late In (m)', 'Early Out (m)', 'Late Out (m)', 'Audit Logs']
            st.dataframe(view_df, use_container_width=True)

        with tab2:
            st.subheader("Payroll Performance (Normalized)")
            st.dataframe(summary, use_container_width=True)
            st.download_button("📥 Export CSV", summary.to_csv(index=False), "payroll_summary.csv")

        with tab3:
            if sel_staff == "All Staff": 
                st.info("Select a specific employee from the sidebar to view their printable slip.")
            elif not sal_id_c or not sal_base_c:
                st.error("Salary columns not detected. Ensure Salary Master has 'ID' and 'Base Salary'.")
            else:
                e_id = str(report[report[staff_name_c] == sel_staff][staff_id_c].iloc[0]).strip()
                df_sal['S_ID'] = df_sal[sal_id_c].astype(str).str.strip()
                e_sal = df_sal[df_sal['S_ID'] == e_id]
                
                if e_sal.empty:
                    st.error(f"No salary data found for ID: {e_id}. Please check your Salary Master CSV.")
                else:
                    base = float(e_sal.iloc[0][sal_base_c])
                    perf = summary[summary[staff_id_c] == e_id].iloc[0]
                    period = len(report['AttendanceDate'].unique())
                    earned = round((base / period) * perf['Final_Payable'], 2)
                    deduction_amount = round((base / period) * perf['Deduction'], 2)
                    
                    color_red = '#e74c3c' if perf['Deduction'] > 0 else '#333'
                    
                    html_slip = (
                        "<div style='border: 2px solid #ccc; padding: 30px; border-radius: 8px; background-color: #ffffff; color: #333; max-width: 700px; margin: auto; font-family: Arial, sans-serif;'>"
                        f"<h2 style='text-align: center; color: #2c3e50; margin-bottom: 5px;'>PAYROLL SLIP</h2>"
                        f"<p style='text-align: center; color: #7f8c8d; margin-top: 0;'>{datetime.now().strftime('%B %Y')}</p>"
                        "<hr style='border-top: 1px solid #eee; margin-bottom: 20px;'>"
                        
                        "<table style='width: 100%; margin-bottom: 20px;'>"
                        f"<tr><td><b>Employee Name:</b> {sel_staff}</td><td style='text-align: right;'><b>Employee ID:</b> {e_id}</td></tr>"
                        f"<tr><td><b>Net Leaves Used:</b> {perf['Net_Leaves']}</td><td style='text-align: right;'><b>Payable Days:</b> {perf['Final_Payable']} / {period}</td></tr>"
                        "</table>"
                        
                        "<div style='background-color: #f8f9fa; padding: 20px; border-radius: 6px;'>"
                        "<table style='width: 100%; border-collapse: collapse;'>"
                        "<tr style='border-bottom: 2px solid #ddd;'>"
                        "<th style='text-align: left; padding-bottom: 10px;'>Earnings / Deductions</th>"
                        "<th style='text-align: right; padding-bottom: 10px;'>Amount</th>"
                        "</tr>"
                        "<tr>"
                        "<td style='padding: 12px 0;'>Base Monthly Salary</td>"
                        f"<td style='text-align: right; padding: 12px 0;'>₹{base:,.2f}</td>"
                        "</tr>"
                        "<tr>"
                        f"<td style='padding: 12px 0; color: {color_red};'>"
                        f"Unpaid Deductions ({perf['Deduction']} Days)<br>"
                        f"<span style='font-size: 0.85em; color: #7f8c8d;'>Policy: {perf['Policy_Note']}</span>"
                        "</td>"
                        f"<td style='text-align: right; padding: 12px 0; color: {color_red};'>"
                        f"-₹{deduction_amount:,.2f}"
                        "</td>"
                        "</tr>"
                        "<tr style='border-top: 2px solid #ddd; font-size: 1.2em; font-weight: bold; color: #27ae60;'>"
                        "<td style='padding-top: 15px;'>NET PAYABLE</td>"
                        f"<td style='text-align: right; padding-top: 15px;'>₹{earned:,.2f}</td>"
                        "</tr>"
                        "</table>"
                        "</div>"
                        "</div>"
                    )
                    
                    st.markdown(html_slip, unsafe_allow_html=True)
                    st.write("") 
                    st.button("🖨️ Print Slip (Ctrl+P)")
