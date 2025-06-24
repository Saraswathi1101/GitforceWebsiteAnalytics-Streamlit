import os
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta
from dateutil.relativedelta import relativedelta
import re
import json

# Set page config to make sidebar narrower
st.set_page_config(
    page_title="Gitforce Analytics",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS to make sidebar narrower
st.markdown("""
<style>
    .css-1d391kg {
        width: 250px;
    }
    .css-1lcbmhc {
        width: 250px;
    }
    .main .block-container {
        padding-left: 2rem;
        padding-right: 2rem;
        max-width: none;
    }
</style>
""", unsafe_allow_html=True)



scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Updated credentials handling for both local and cloud deployment
def get_google_credentials():
    try:
        # Try to load from Streamlit secrets (for cloud deployment)
        if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
            credentials_dict = {
                "type": st.secrets["gcp_service_account"]["type"],
                "project_id": st.secrets["gcp_service_account"]["project_id"],
                "private_key_id": st.secrets["gcp_service_account"]["private_key_id"],
                "private_key": st.secrets["gcp_service_account"]["private_key"],
                "client_email": st.secrets["gcp_service_account"]["client_email"],
                "client_id": st.secrets["gcp_service_account"]["client_id"],
                "auth_uri": st.secrets["gcp_service_account"]["auth_uri"],
                "token_uri": st.secrets["gcp_service_account"]["token_uri"],
                "auth_provider_x509_cert_url": st.secrets["gcp_service_account"]["auth_provider_x509_cert_url"],
                "client_x509_cert_url": st.secrets["gcp_service_account"]["client_x509_cert_url"]
            }
            return Credentials.from_service_account_info(credentials_dict, scopes=scope)
        else:
            # Fallback to local file (for local development)
            return Credentials.from_service_account_file("credentials.json", scopes=scope)
    except Exception as e:
        st.error(f"Error loading credentials: {str(e)}")
        st.stop()

# Get credentials and authorize client
try:
    creds = get_google_credentials()
    client = gspread.authorize(creds)
    
    # Load data with error handling
    workbook = client.open("Clarity Data")
    worksheet = workbook.worksheet("Downloaded data")
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)
    
    if df.empty:
        st.error("No data found in the Google Sheet.")
        st.stop()
        
except Exception as e:
    st.error(f"Error connecting to Google Sheets: {str(e)}")
    st.error("Please check your credentials and sheet permissions.")
    st.stop()

# workbook = client.open("Clarity Data")
# worksheet = workbook.worksheet("Downloaded data")
# data = worksheet.get_all_records()
# df = pd.DataFrame(data)

df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors='coerce')
df = df[df["Date"].notnull()]
df = df[df["Clarity user ID"].notnull()]
df["Device"] = df["Device"].fillna("Unknown")
df["Country"] = df["Country"].fillna("Unknown")

# Handle OS column
if "OS" not in df.columns:
    df["OS"] = "Unknown"
else:
    df["OS"] = df["OS"].fillna("Unknown")

# Handle Referrer column
if "Referrer" not in df.columns:
    df["Referrer"] = "Direct"
else:
    df["Referrer"] = df["Referrer"].fillna("Direct")
    df["Referrer"] = df["Referrer"].replace("", "Direct")

# Handle Page count column
if 'Page count' not in df.columns:
    st.warning("Page count column not found. Using default value of 1.")
    df['Page count'] = 1

# Handle Clicks column (if it exists)
if 'Clicks' not in df.columns:
    df['Clicks'] = 0
else:
    df['Clicks'] = df['Clicks'].fillna(0)


def duration_to_seconds(duration_str):
    if pd.isna(duration_str) or duration_str == "":
        return 0

    duration_str = str(duration_str).strip()
    colon_count = duration_str.count(':')

    try:
        if colon_count == 1:  # mm:ss format
            parts = duration_str.split(':')
            minutes = int(parts[0])
            seconds = int(parts[1])
            return (minutes * 60) + seconds
        elif colon_count == 2:  # hh:mm:ss format
            parts = duration_str.split(':')
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
            return (hours * 3600) + (minutes * 60) + seconds
        else:
            return 0
    except:
        return 0


if 'Session duration' in df.columns:
    df['TotalSeconds'] = df['Session duration'].apply(duration_to_seconds)
else:
    st.warning("Session duration column not found. Using default value of 0.")
    df['TotalSeconds'] = 0

# Page Selection
page = st.sidebar.selectbox("Select Page", ["Overview", "User Insights"])

# Common Filters for User Insights page
if page == "User Insights":
    st.sidebar.title("Filters")

    # Date Range
    min_date = df["Date"].min()
    max_date = df["Date"].max()
    start_date, end_date = st.sidebar.date_input("Select date range", [min_date, max_date],
                                                 min_value=min_date, max_value=max_date)

    # Country Filter
    all_countries = sorted(df["Country"].unique())
    selected_countries = st.sidebar.multiselect("Select Country", all_countries, default=all_countries)

    # Device Filter
    all_devices = sorted(df["Device"].unique())
    selected_devices = st.sidebar.multiselect("Select Device", all_devices, default=all_devices)


def format_duration(total_seconds):
    if total_seconds == 0:
        return "-"

    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)

    if hours > 0:
        return f"{hours}h{minutes}m"
    elif minutes > 0:
        return f"{minutes}m{seconds}s"
    else:
        return f"{seconds}s"


def get_comparison_dates(start_date, end_date, comparison_type):
    """Fixed comparison date calculation"""
    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)

    # Calculate the number of days in the selected period (inclusive)
    period_length = (end_date - start_date).days + 1

    if comparison_type == "Last Trailing Period":
        # For trailing period: go back by the same number of days
        # If current period is June 1-10 (10 days), trailing period should be May 22-31 (10 days)
        comp_end_date = start_date - timedelta(days=1)  # Day before start date
        comp_start_date = comp_end_date - timedelta(days=period_length - 1)  # Go back period_length days

    else:  # Same Period Last Month
        # For same period last month: same dates but previous month
        # If current period is June 1-10, comparison period is May 1-10
        try:
            # Use relativedelta for proper month arithmetic
            comp_start_date = start_date - relativedelta(months=1)
            comp_end_date = end_date - relativedelta(months=1)
        except:
            # Fallback to simple subtraction if relativedelta fails
            if start_date.month == 1:
                comp_start_date = start_date.replace(year=start_date.year - 1, month=12)
                comp_end_date = end_date.replace(year=end_date.year - 1, month=12)
            else:
                comp_start_date = start_date.replace(month=start_date.month - 1)
                comp_end_date = end_date.replace(month=end_date.month - 1)

    return comp_start_date, comp_end_date


def calculate_kpis(filtered_df, df_all, period_start=None, period_end=None):
    """Calculate all KPIs for a given filtered dataframe"""
    kpis = {}

    if len(filtered_df) == 0:
        # Return zero values if no data
        return {
            'unique_users': 0,
            'new_users': 0,
            'total_sessions': 0,
            'returning_users': 0,
            'avg_duration': 0,
            'avg_duration_formatted': '-',
            'page_views': 0,
            'bounce_rate': 0
        }

    # Use provided period dates or fall back to actual data range
    if period_start is not None and period_end is not None:
        filter_start = pd.to_datetime(period_start)
        filter_end = pd.to_datetime(period_end)
    else:
        filter_start = filtered_df["Date"].min()
        filter_end = filtered_df["Date"].max()

    # 1. Unique Users
    kpis['unique_users'] = filtered_df["Clarity user ID"].nunique()

    # 2. New Users - users whose first appearance is within the filtered period
    first_seen_dates = df_all.groupby("Clarity user ID")["Date"].min().reset_index(name="first_seen")

    # Find users who first appeared in this period
    new_users_in_period = first_seen_dates[
        (first_seen_dates["first_seen"] >= filter_start) &
        (first_seen_dates["first_seen"] <= filter_end)
        ]

    # Count how many of these new users are in our filtered data
    kpis['new_users'] = filtered_df[
        filtered_df["Clarity user ID"].isin(new_users_in_period["Clarity user ID"])
    ]["Clarity user ID"].nunique()

    # 3. Total Sessions
    kpis['total_sessions'] = len(filtered_df)

    # 4. Returning Users
    # Count sessions per user in the filtered period
    user_sessions = filtered_df.groupby("Clarity user ID").size().reset_index(name="session_count")

    # New users with multiple sessions in the current period
    new_returning = user_sessions[user_sessions["session_count"] > 1]["Clarity user ID"].nunique()

    # Existing users (first seen before filter period) who are active in the period
    existing_users = first_seen_dates[first_seen_dates["first_seen"] < filter_start]["Clarity user ID"]
    existing_returning = filtered_df[
        filtered_df["Clarity user ID"].isin(existing_users)
    ]["Clarity user ID"].nunique()

    kpis['returning_users'] = new_returning + existing_returning

    # 5. Average Session Duration
    avg_duration_seconds = filtered_df['TotalSeconds'].mean()
    kpis['avg_duration'] = avg_duration_seconds
    kpis['avg_duration_formatted'] = format_duration(avg_duration_seconds)

    # 6. Page Views
    kpis['page_views'] = filtered_df['Page count'].sum()

    # 7. Bounce Rate
    user_page_counts = filtered_df.groupby("Clarity user ID")['Page count'].sum().reset_index()
    users_with_one_page = len(user_page_counts[user_page_counts['Page count'] == 1])
    total_unique_users = kpis['unique_users']
    kpis['bounce_rate'] = (users_with_one_page / total_unique_users) * 100 if total_unique_users > 0 else 0

    return kpis


def display_comparison_metric(label, current_value, comparison_value, format_type="number"):
    """Display metric with comparison"""
    if comparison_value == 0:
        change_pct = 0
    else:
        change_pct = ((current_value - comparison_value) / comparison_value) * 100

    # Format values based on type
    if format_type == "duration":
        current_display = format_duration(current_value)
        comparison_display = format_duration(comparison_value)
    elif format_type == "percentage":
        current_display = f"{current_value:.1f}%"
        comparison_display = f"{comparison_value:.1f}%"
    else:
        current_display = f"{current_value:,}"
        comparison_display = f"{comparison_value:,}"

    # Determine color and arrow
    if change_pct > 0:
        color = "green"
        arrow = "↗"
    elif change_pct < 0:
        color = "red"
        arrow = "↘"
    else:
        color = "gray"
        arrow = "→"

    st.markdown(f"""
    <div style="background-color: #f0f2f6; padding: 15px; border-radius: 10px; margin: 5px 0;">
        <h4 style="margin: 0; color: #1f1f1f;">{label}</h4>
        <h2 style="margin: 5px 0; color: #1f1f1f;">{current_display}</h2>
        <p style="margin: 0; color: {color}; font-weight: bold;">
            {arrow} {change_pct:+.1f}% ({comparison_display})
        </p>
    </div>
    """, unsafe_allow_html=True)


# PAGE 1: OVERVIEW
if page == "Overview":
    # Sidebar Filters for Overview
    st.sidebar.title("Filters")

    # Date Range
    min_date = df["Date"].min()
    max_date = df["Date"].max()
    start_date, end_date = st.sidebar.date_input("Select date range", [min_date, max_date], min_value=min_date,
                                                 max_value=max_date)

    # Country Filter
    all_countries = sorted(df["Country"].unique())
    selected_countries = st.sidebar.multiselect("Select Country", all_countries, default=all_countries)

    # Device Filter
    all_devices = sorted(df["Device"].unique())
    selected_devices = st.sidebar.multiselect("Select Device", all_devices, default=all_devices)

    # Comparison Filter
    comparison_type = st.sidebar.selectbox("Comparison Period", ["Last Trailing Period", "Same Period Last Month"])

    # Apply Filters for current period
    filtered_df = df.copy()
    filtered_df = filtered_df[
        (filtered_df["Date"] >= pd.to_datetime(start_date)) &
        (filtered_df["Date"] <= pd.to_datetime(end_date)) &
        (filtered_df["Country"].isin(selected_countries)) &
        (filtered_df["Device"].isin(selected_devices))
        ]

    # Get comparison period dates and filter
    comp_start_date, comp_end_date = get_comparison_dates(start_date, end_date, comparison_type)
    comparison_df = df.copy()
    comparison_df = comparison_df[
        (comparison_df["Date"] >= comp_start_date) &
        (comparison_df["Date"] <= comp_end_date) &
        (comparison_df["Country"].isin(selected_countries)) &
        (comparison_df["Device"].isin(selected_devices))
        ]

    # Calculate KPIs for both periods
    current_kpis = calculate_kpis(filtered_df, df, start_date, end_date)
    comparison_kpis = calculate_kpis(comparison_df, df, comp_start_date, comp_end_date)

    # Layout
    st.title("Gitforce Website Analytics - Overview")

    # Display current date range
    st.markdown(f"**Current Period:** {start_date} to {end_date}")
    st.markdown(
        f"**Comparison Period ({comparison_type}):** {comp_start_date.strftime('%Y-%m-%d')} to {comp_end_date.strftime('%Y-%m-%d')}")

    st.markdown("---")

    # KPI Cards
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        display_comparison_metric("Unique Users", current_kpis['unique_users'], comparison_kpis['unique_users'])

    with col2:
        display_comparison_metric("New Users", current_kpis['new_users'], comparison_kpis['new_users'])

    with col3:
        display_comparison_metric("Total Sessions", current_kpis['total_sessions'], comparison_kpis['total_sessions'])

    with col4:
        display_comparison_metric("Returning Users", current_kpis['returning_users'],
                                  comparison_kpis['returning_users'])

    col5, col6, col7 = st.columns(3)

    with col5:
        display_comparison_metric("Avg Session Duration", current_kpis['avg_duration'], comparison_kpis['avg_duration'],
                                  "duration")

    with col6:
        display_comparison_metric("Page Views", current_kpis['page_views'], comparison_kpis['page_views'])

    with col7:
        display_comparison_metric("Bounce Rate", current_kpis['bounce_rate'], comparison_kpis['bounce_rate'],
                                  "percentage")

    st.markdown("---")

    # Additional Visualizations
    st.markdown("## Detailed Analytics")

    # Row 1: Device and OS Breakdown
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Device Breakdown by Sessions")
        if len(filtered_df) > 0:
            device_sessions = filtered_df['Device'].value_counts().reset_index()
            device_sessions.columns = ['Device', 'Sessions']

            fig_device = px.pie(
                device_sessions,
                values='Sessions',
                names='Device',
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Set3
            )
            fig_device.update_traces(textposition='inside', textinfo='percent+label')
            fig_device.update_layout(
                showlegend=True,
                height=400,
                margin=dict(t=0, b=0, l=0, r=0)
            )
            st.plotly_chart(fig_device, use_container_width=True)
        else:
            st.info("No data available for the selected filters.")

    with col2:
        st.markdown("### OS Breakdown by Sessions")
        if len(filtered_df) > 0:
            os_sessions = filtered_df['OS'].value_counts().reset_index()
            os_sessions.columns = ['Operating System', 'Sessions']

            fig_os = px.pie(
                os_sessions,
                values='Sessions',
                names='Operating System',
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_os.update_traces(textposition='inside', textinfo='percent+label')
            fig_os.update_layout(
                showlegend=True,
                height=400,
                margin=dict(t=0, b=0, l=0, r=0)
            )
            st.plotly_chart(fig_os, use_container_width=True)
        else:
            st.info("No data available for the selected filters.")

    # Row 2: Country Breakdown Table
    st.markdown("### Country Breakdown")
    if len(filtered_df) > 0:
        # Calculate country metrics
        country_metrics = []

        for country in filtered_df['Country'].unique():
            country_data = filtered_df[filtered_df['Country'] == country]

            # Calculate metrics for this country
            country_kpis = calculate_kpis(country_data, df, start_date, end_date)

            country_metrics.append({
                'Country': country,
                'Total Unique Users': country_kpis['unique_users'],
                'New Users': country_kpis['new_users'],
                'Sessions': country_kpis['total_sessions'],
                'Time Spent': format_duration(country_data['TotalSeconds'].sum())
            })

        # Convert to DataFrame and sort by sessions
        country_df = pd.DataFrame(country_metrics)
        country_df = country_df.sort_values('Sessions', ascending=False)

        # Display the table
        st.dataframe(
            country_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Country": st.column_config.TextColumn("Country", width="medium"),
                "Total Unique Users": st.column_config.NumberColumn("Total Unique Users", format="%d"),
                "New Users": st.column_config.NumberColumn("New Users", format="%d"),
                "Sessions": st.column_config.NumberColumn("Sessions", format="%d"),
                "Time Spent": st.column_config.TextColumn("Time Spent", width="medium")
            }
        )
    else:
        st.info("No data available for the selected filters.")

    # Row 3: Top Referrers
    st.markdown("### Top Referrers by Sessions")
    if len(filtered_df) > 0:
        referrer_sessions = filtered_df['Referrer'].value_counts().reset_index()
        referrer_sessions.columns = ['Referrer', 'Sessions']

        # Take top 10 referrers
        top_referrers = referrer_sessions.head(10)

        # Create horizontal bar chart
        fig_referrers = px.bar(
            top_referrers.sort_values('Sessions', ascending=True),  # Sort ascending for horizontal bar
            x='Sessions',
            y='Referrer',
            orientation='h',
            color='Sessions',
            color_continuous_scale='Blues',
            text='Sessions'
        )

        fig_referrers.update_traces(textposition='outside')
        fig_referrers.update_layout(
            height=400,
            showlegend=False,
            xaxis_title="Number of Sessions",
            yaxis_title="Referrer",
            coloraxis_showscale=False,
            margin=dict(l=150, r=50, t=50, b=50)
        )

        st.plotly_chart(fig_referrers, use_container_width=True)
    else:
        st.info("No data available for the selected filters.")

# PAGE 2: USER INSIGHTS
elif page == "User Insights":
    # Apply Filters for User Insights
    filtered_df = df.copy()
    filtered_df = filtered_df[
        (filtered_df["Date"] >= pd.to_datetime(start_date)) &
        (filtered_df["Date"] <= pd.to_datetime(end_date)) &
        (filtered_df["Country"].isin(selected_countries)) &
        (filtered_df["Device"].isin(selected_devices))
        ]

    st.title("Gitforce Website Analytics - User Insights")

    # Display current date range
    st.markdown(f"**Period:** {start_date} to {end_date}")
    st.markdown("---")

    if len(filtered_df) > 0:
        # 1. Top 10 Users Table
        st.markdown("###  Top 10 Users")

        # Calculate user metrics
        user_metrics = filtered_df.groupby('Clarity user ID').agg({
            'Country': 'first',
            'Device': 'first',
            'Referrer': 'first',
            'Date': 'count',  # Sessions count
            'Clicks': 'sum',  # Total clicks
            'Page count': 'sum'  # Total page views
        }).reset_index()

        user_metrics.columns = ['Clarity User ID', 'Country', 'Device', 'Referrer', 'Sessions', 'Session Clicks',
                                'Page Views']
        user_metrics = user_metrics.sort_values('Sessions', ascending=False).head(10)

        st.dataframe(
            user_metrics,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Clarity User ID": st.column_config.TextColumn("Clarity User ID", width="medium"),
                "Country": st.column_config.TextColumn("Country", width="small"),
                "Device": st.column_config.TextColumn("Device", width="small"),
                "Referrer": st.column_config.TextColumn("Referrer", width="medium"),
                "Sessions": st.column_config.NumberColumn("Sessions", format="%d"),
                "Session Clicks": st.column_config.NumberColumn("Session Clicks", format="%d"),
                "Page Views": st.column_config.NumberColumn("Page Views", format="%d")
            }
        )

        st.markdown("---")

        # 2. New Users Table
        st.markdown("### New Users")

        # Find new users (first appearance in the filtered period)
        first_seen_dates = df.groupby("Clarity user ID")["Date"].min().reset_index(name="first_seen")
        new_users_in_period = first_seen_dates[
            (first_seen_dates["first_seen"] >= pd.to_datetime(start_date)) &
            (first_seen_dates["first_seen"] <= pd.to_datetime(end_date))
            ]

        # Get new users data from filtered dataframe
        new_users_data = filtered_df[
            filtered_df["Clarity user ID"].isin(new_users_in_period["Clarity user ID"])
        ]

        if len(new_users_data) > 0:
            # Get latest visit date for each new user
            new_user_metrics = new_users_data.groupby('Clarity user ID').agg({
                'Country': 'first',
                'Device': 'first',
                'Referrer': 'first',
                'Date': 'max'  # Latest date
            }).reset_index()

            new_user_metrics.columns = ['Clarity User ID', 'Country', 'Device', 'Referrer', 'Latest Visit Date']
            new_user_metrics = new_user_metrics.sort_values('Latest Visit Date', ascending=False)

            st.dataframe(
                new_user_metrics,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Clarity User ID": st.column_config.TextColumn("Clarity User ID", width="medium"),
                    "Country": st.column_config.TextColumn("Country", width="small"),
                    "Device": st.column_config.TextColumn("Device", width="small"),
                    "Referrer": st.column_config.TextColumn("Referrer", width="medium"),
                    "Latest Visit Date": st.column_config.DateColumn("Latest Visit Date")
                }
            )
        else:
            st.info("No new users found in the selected period.")

        st.markdown("---")

        # 3. Unique User Sessions Over Time
        st.markdown("###  Unique User Sessions Over Time")

        daily_sessions = filtered_df.groupby('Date').size().reset_index(name='Total Sessions')

        fig_time = px.line(
            daily_sessions,
            x='Date',
            y='Total Sessions',
            title='Daily Session Count',
            markers=True
        )

        fig_time.update_layout(
            height=400,
            xaxis_title="Date",
            yaxis_title="Total Sessions",
            hovermode='x unified'
        )

        st.plotly_chart(fig_time, use_container_width=True)

        st.markdown("---")

        # 4. Unique User Sessions Over Weekdays
        st.markdown("### Unique User Sessions by Weekday")

        # Add weekday column
        filtered_df_weekday = filtered_df.copy()
        filtered_df_weekday['Weekday'] = filtered_df_weekday['Date'].dt.day_name()

        # Define weekday order
        weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

        weekday_sessions = filtered_df_weekday.groupby('Weekday').size().reset_index(name='Total Sessions')
        weekday_sessions['Weekday'] = pd.Categorical(weekday_sessions['Weekday'], categories=weekday_order,
                                                     ordered=True)
        weekday_sessions = weekday_sessions.sort_values('Weekday')

        fig_weekday = px.line(
            weekday_sessions,
            x='Weekday',
            y='Total Sessions',
            title='Sessions by Weekday',
            markers=True
        )

        fig_weekday.update_layout(
            height=400,
            xaxis_title="Weekday",
            yaxis_title="Total Sessions",
            hovermode='x unified'
        )

        st.plotly_chart(fig_weekday, use_container_width=True)

    else:
        st.info("No data available for the selected filters.")



