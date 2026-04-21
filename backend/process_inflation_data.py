#!/usr/bin/env python3
"""
Process inflation expectation data from FRED.
Align T5YIFR (5-Year, 5-Year Forward Inflation Expectation Rate) and 
T10YIE (10-Year Breakeven Inflation Rate) on common dates.
Calculate differences and identify divergence periods.
"""

import pandas as pd
import numpy as np
from datetime import datetime
import json
import os

def load_and_process_data():
    """Load both inflation series and process them."""
    
    # File paths
    t5yifr_path = "/home/vorndranj/projects/DeepResearchAgent/backend/data/job_a3e0d30b/T5YIFR_inflation_expectation_rate_job_a3e0d30b.csv"
    t10yie_path = "/home/vorndranj/projects/DeepResearchAgent/backend/data/job_a3e0d30b/T10YIE_breakeven_inflation_rate_job_a3e0d30b.csv"
    
    # Output path
    output_dir = "/home/vorndranj/projects/DeepResearchAgent/backend/outputs/job_inflation_comparison"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "processed_data.csv")
    
    print(f"Loading T5YIFR from: {t5yifr_path}")
    print(f"Loading T10YIE from: {t10yie_path}")
    
    # Load data
    df_t5yifr = pd.read_csv(t5yifr_path)
    df_t10yie = pd.read_csv(t10yie_path)
    
    print(f"T5YIFR shape: {df_t5yifr.shape}")
    print(f"T10YIE shape: {df_t10yie.shape}")
    
    # Clean data - convert date and value columns
    df_t5yifr['date'] = pd.to_datetime(df_t5yifr['date'])
    df_t10yie['date'] = pd.to_datetime(df_t10yie['date'])
    
    # Convert value to numeric, coerce errors to NaN
    df_t5yifr['value'] = pd.to_numeric(df_t5yifr['value'], errors='coerce')
    df_t10yie['value'] = pd.to_numeric(df_t10yie['value'], errors='coerce')
    
    # Filter to requested date range (2014-01-01 to 2024-12-31)
    start_date = pd.Timestamp('2014-01-01')
    end_date = pd.Timestamp('2024-12-31')
    
    df_t5yifr = df_t5yifr[(df_t5yifr['date'] >= start_date) & (df_t5yifr['date'] <= end_date)]
    df_t10yie = df_t10yie[(df_t10yie['date'] >= start_date) & (df_t10yie['date'] <= end_date)]
    
    print(f"After date filtering:")
    print(f"T5YIFR shape: {df_t5yifr.shape}")
    print(f"T10YIE shape: {df_t10yie.shape}")
    
    # Merge on common dates (inner join)
    merged = pd.merge(
        df_t5yifr[['date', 'value']].rename(columns={'value': 'forward_rate'}),
        df_t10yie[['date', 'value']].rename(columns={'value': 'breakeven_rate'}),
        on='date',
        how='inner'
    )
    
    print(f"Merged data shape: {merged.shape}")
    
    # Calculate difference: Forward_Expectation - Breakeven_Rate
    merged['difference'] = merged['forward_rate'] - merged['breakeven_rate']
    
    # Sort by date
    merged = merged.sort_values('date').reset_index(drop=True)
    
    # Identify periods where difference exceeds +0.5% for at least 3 consecutive months
    # First, create a monthly resampled version for the 3-month check
    merged_monthly = merged.copy()
    merged_monthly['year_month'] = merged_monthly['date'].dt.to_period('M')
    monthly_avg = merged_monthly.groupby('year_month').agg({
        'difference': 'mean',
        'forward_rate': 'mean',
        'breakeven_rate': 'mean'
    }).reset_index()
    
    # Find periods with difference > 0.5
    monthly_avg['above_threshold'] = monthly_avg['difference'] > 0.5
    
    # Identify consecutive months above threshold
    divergence_periods = []
    current_start = None
    current_count = 0
    
    for idx, row in monthly_avg.iterrows():
        if row['above_threshold']:
            if current_start is None:
                current_start = row['year_month']
            current_count += 1
        else:
            if current_count >= 3:  # At least 3 consecutive months
                divergence_periods.append({
                    'start_date': current_start.strftime('%Y-%m'),
                    'end_date': monthly_avg.iloc[idx-1]['year_month'].strftime('%Y-%m'),
                    'duration_months': current_count,
                    'avg_difference': monthly_avg.loc[idx-current_count:idx-1, 'difference'].mean()
                })
            current_start = None
            current_count = 0
    
    # Check if last period extends to end
    if current_count >= 3:
        divergence_periods.append({
            'start_date': current_start.strftime('%Y-%m'),
            'end_date': monthly_avg.iloc[-1]['year_month'].strftime('%Y-%m'),
            'duration_months': current_count,
            'avg_difference': monthly_avg.loc[len(monthly_avg)-current_count:, 'difference'].mean()
        })
    
    # Calculate summary statistics (convert numpy types to Python native types)
    summary_stats = {
        'forward_rate': {
            'mean': float(merged['forward_rate'].mean()),
            'median': float(merged['forward_rate'].median()),
            'std': float(merged['forward_rate'].std()),
            'min': float(merged['forward_rate'].min()),
            'max': float(merged['forward_rate'].max()),
            'count': int(merged['forward_rate'].count())
        },
        'breakeven_rate': {
            'mean': float(merged['breakeven_rate'].mean()),
            'median': float(merged['breakeven_rate'].median()),
            'std': float(merged['breakeven_rate'].std()),
            'min': float(merged['breakeven_rate'].min()),
            'max': float(merged['breakeven_rate'].max()),
            'count': int(merged['breakeven_rate'].count())
        },
        'difference': {
            'mean': float(merged['difference'].mean()),
            'median': float(merged['difference'].median()),
            'std': float(merged['difference'].std()),
            'min': float(merged['difference'].min()),
            'max': float(merged['difference'].max()),
            'count': int(merged['difference'].count())
        }
    }
    
    # Save processed data
    merged.to_csv(output_path, index=False)
    print(f"Processed data saved to: {output_path}")
    print(f"Row count: {len(merged)}")
    print(f"Date range: {merged['date'].min()} to {merged['date'].max()}")
    
    # Prepare metadata
    metadata = {
        'file_path': output_path,
        'row_count': int(len(merged)),
        'date_range': {
            'start': str(merged['date'].min().strftime('%Y-%m-%d')),
            'end': str(merged['date'].max().strftime('%Y-%m-%d'))
        },
        'data_sources': [
            {
                'provider': 'FRED',
                'description': '5-Year, 5-Year Forward Inflation Expectation Rate',
                'series_id': 'T5YIFR',
                'date_range': f"{df_t5yifr['date'].min().strftime('%Y-%m-%d')} to {df_t5yifr['date'].max().strftime('%Y-%m-%d')}",
                'row_count': int(len(df_t5yifr))
            },
            {
                'provider': 'FRED',
                'description': '10-Year Breakeven Inflation Rate',
                'series_id': 'T10YIE',
                'date_range': f"{df_t10yie['date'].min().strftime('%Y-%m-%d')} to {df_t10yie['date'].max().strftime('%Y-%m-%d')}",
                'row_count': int(len(df_t10yie))
            }
        ],
        'divergence_periods': divergence_periods,
        'summary_stats': summary_stats
    }
    
    # Save metadata as JSON
    metadata_path = os.path.join(output_dir, "metadata.json")
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"Metadata saved to: {metadata_path}")
    
    return merged, metadata

if __name__ == "__main__":
    df, metadata = load_and_process_data()
    
    print("\n=== Processing Complete ===")
    print(f"Aligned data points: {len(df)}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"\nDivergence periods (difference > 0.5% for ≥3 months):")
    for period in metadata['divergence_periods']:
        print(f"  {period['start_date']} to {period['end_date']} ({period['duration_months']} months, avg diff: {period['avg_difference']:.3f}%)")
    
    print(f"\nSummary Statistics:")
    print(f"Forward Rate: mean={metadata['summary_stats']['forward_rate']['mean']:.3f}%, std={metadata['summary_stats']['forward_rate']['std']:.3f}%")
    print(f"Breakeven Rate: mean={metadata['summary_stats']['breakeven_rate']['mean']:.3f}%, std={metadata['summary_stats']['breakeven_rate']['std']:.3f}%")
    print(f"Difference: mean={metadata['summary_stats']['difference']['mean']:.3f}%, std={metadata['summary_stats']['difference']['std']:.3f}%")