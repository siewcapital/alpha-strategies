"""
Data Fetcher for Token Unlock Events
=====================================
Fetches unlock schedules from various sources.

Data Sources:
1. CoinGecko API (free tier)
2. TokenUnlocks.app API
3. Manual CSV imports
4. On-chain data (subgraphs)

Priority: TokenUnlocks.app > CoinGecko > Manual
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
import json
import time


class CoinGeckoDataSource:
    """Fetch token data from CoinGecko API."""
    
    BASE_URL = "https://api.coingecko.com/api/v3"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({
                "x-cg-pro-api-key": api_key
            })
    
    def get_circulating_supply(self, token_id: str) -> Optional[float]:
        """Get current circulating supply for a token."""
        try:
            url = f"{self.BASE_URL}/coins/{token_id}"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            return data.get('market_data', {}).get('circulating_supply')
        
        except Exception as e:
            print(f"Error fetching supply for {token_id}: {e}")
            return None
    
    def get_token_list(self) -> List[Dict]:
        """Get list of all supported tokens."""
        try:
            url = f"{self.BASE_URL}/coins/list"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        
        except Exception as e:
            print(f"Error fetching token list: {e}")
            return []
    
    def get_market_data(self, token_ids: List[str]) -> pd.DataFrame:
        """Get market data for multiple tokens."""
        try:
            ids = ",".join(token_ids)
            url = f"{self.BASE_URL}/coins/markets"
            params = {
                'vs_currency': 'usd',
                'ids': ids,
                'order': 'market_cap_desc',
                'per_page': 250,
                'page': 1,
                'sparkline': False
            }
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            return pd.DataFrame(data)
        
        except Exception as e:
            print(f"Error fetching market data: {e}")
            return pd.DataFrame()


class TokenUnlocksDataSource:
    """
    Token unlock data from TokenUnlocks.app.
    
    Note: This is a premium API. Without API key, falls back to
    scraping or manual data imports.
    """
    
    BASE_URL = "https://api.tokenunlocks.app/v1"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {api_key}"
            })
    
    def get_unlock_schedule(self, token: str) -> List[Dict]:
        """Get unlock schedule for a specific token."""
        if not self.api_key:
            print("No API key provided for TokenUnlocks")
            return []
        
        try:
            url = f"{self.BASE_URL}/unlock-schedule/{token}"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.json().get('unlocks', [])
        
        except Exception as e:
            print(f"Error fetching unlock schedule: {e}")
            return []
    
    def get_all_upcoming_unlocks(self, days: int = 90) -> List[Dict]:
        """Get all upcoming unlocks in next N days."""
        if not self.api_key:
            print("No API key provided for TokenUnlocks")
            return []
        
        try:
            url = f"{self.BASE_URL}/upcoming-unlocks"
            params = {'days': days}
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json().get('unlocks', [])
        
        except Exception as e:
            print(f"Error fetching upcoming unlocks: {e}")
            return []


class DataAggregator:
    """
    Aggregate unlock data from multiple sources.
    
    Usage:
        aggregator = DataAggregator()
        unlocks = aggregator.get_all_unlocks()
    """
    
    def __init__(
        self,
        coingecko_key: Optional[str] = None,
        tokenunlocks_key: Optional[str] = None
    ):
        self.coingecko = CoinGeckoDataSource(coingecko_key)
        self.tokenunlocks = TokenUnlocksDataSource(tokenunlocks_key)
        
    def get_all_unlocks(
        self,
        tokens: Optional[List[str]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        Get consolidated unlock data.
        
        Returns DataFrame with columns:
        - token
        - unlock_date
        - unlock_amount
        - circulating_supply
        - unlock_pct
        - source
        """
        all_unlocks = []
        
        # Try TokenUnlocks first (most accurate)
        if self.tokenunlocks.api_key:
            print("Fetching from TokenUnlocks.app...")
            upcoming = self.tokenunlocks.get_all_upcoming_unlocks(days=365)
            all_unlocks.extend(upcoming)
        
        # Try CoinGecko for circulating supply data
        if tokens:
            print(f"Fetching circulating supply for {len(tokens)} tokens...")
            for token in tokens:
                supply = self.coingecko.get_circulating_supply(token)
                if supply:
                    # Match with unlock data
                    for unlock in all_unlocks:
                        if unlock.get('token') == token:
                            unlock['circulating_supply'] = supply
                time.sleep(1.2)  # Rate limit
        
        df = pd.DataFrame(all_unlocks)
        
        # Calculate unlock percentage
        if not df.empty and 'circulating_supply' in df.columns:
            df['unlock_pct'] = (df['unlock_amount'] / df['circulating_supply']) * 100
        
        # Filter by date if provided
        if start_date and 'unlock_date' in df.columns:
            df['unlock_date'] = pd.to_datetime(df['unlock_date'])
            df = df[df['unlock_date'] >= start_date]
        
        if end_date and 'unlock_date' in df.columns:
            df = df[df['unlock_date'] <= end_date]
        
        return df
    
    def load_manual_data(self, filepath: str) -> pd.DataFrame:
        """Load unlock data from CSV file."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        
        df = pd.read_csv(filepath)
        
        # Standardize column names
        df.columns = df.columns.str.lower().str.strip()
        
        # Parse dates
        if 'unlock_date' in df.columns:
            df['unlock_date'] = pd.to_datetime(df['unlock_date'])
        
        # Calculate unlock_pct if not present
        if 'unlock_pct' not in df.columns and 'unlock_amount' in df.columns:
            df['unlock_pct'] = (df['unlock_amount'] / df['circulating_supply']) * 100
        
        return df
    
    def save_to_csv(self, df: pd.DataFrame, filepath: str):
        """Save unlock data to CSV."""
        df.to_csv(filepath, index=False)
        print(f"Saved {len(df)} unlock records to {filepath}")


# Sample unlock data (for backtesting without API)
SAMPLE_UNLOCK_DATA = [
    # Format: token, unlock_date, unlock_amount, circulating_supply
    {"token": "SOL", "unlock_date": "2024-03-01", "unlock_amount": 5_000_000, "circulating_supply": 443_000_000},
    {"token": "SOL", "unlock_date": "2024-06-01", "unlock_amount": 8_000_000, "circulating_supply": 448_000_000},
    {"token": "AVAX", "unlock_date": "2024-02-15", "unlock_amount": 9_500_000, "circulating_supply": 377_000_000},
    {"token": "UNI", "unlock_date": "2024-04-01", "unlock_amount": 15_000_000, "circulating_supply": 600_000_000},
    {"token": "ARB", "unlock_date": "2024-03-16", "unlock_amount": 1_200_000_000, "circulating_supply": 1_275_000_000},
    {"token": "OP", "unlock_date": "2024-05-31", "unlock_amount": 150_000_000, "circulating_supply": 1_000_000_000},
    {"token": "SUI", "unlock_date": "2024-04-03", "unlock_amount": 600_000_000, "circulating_supply": 1_200_000_000},
    {"token": "APT", "unlock_date": "2024-03-12", "unlock_amount": 25_000_000, "circulating_supply": 400_000_000},
    {"token": "DYDX", "unlock_date": "2024-02-01", "unlock_amount": 150_000_000, "circulating_supply": 350_000_000},
    {"token": "AXS", "unlock_date": "2024-05-01", "unlock_amount": 20_000_000, "circulating_supply": 140_000_000},
    {"token": "IMX", "unlock_date": "2024-03-15", "unlock_amount": 180_000_000, "circulating_supply": 1_400_000_000},
]


if __name__ == "__main__":
    # Demo usage
    print("Token Unlock Data Fetcher Demo")
    print("="*60)
    
    # Use sample data
    df = pd.DataFrame(SAMPLE_UNLOCK_DATA)
    df['unlock_date'] = pd.to_datetime(df['unlock_date'])
    df['unlock_pct'] = (df['unlock_amount'] / df['circulating_supply']) * 100
    
    print("\nSample Unlock Data:")
    print(df.to_string())
    print(f"\nSignificant unlocks (≥1%): {(df['unlock_pct'] >= 1).sum()}")
    
    # Save sample
    df.to_csv('data/sample_unlocks.csv', index=False)
    print("\nSaved to data/sample_unlocks.csv")
