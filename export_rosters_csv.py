"""Export US Open Pool Rosters 2026 from Excel to flat CSV (expands the $0.25 Amateur Pod)."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import os, glob

DIR = os.path.dirname(os.path.abspath(__file__))
# Pick the most recently modified rosters workbook so newly added rosters
# (e.g. "... 2026 (1).xlsx") are used automatically. Skip Excel ~$ temp files.
_candidates = [f for f in glob.glob(os.path.join(DIR, 'US Open Pool Rosters 2026*.xlsx'))
               if not os.path.basename(f).startswith('~$')]
XLSX = max(_candidates, key=os.path.getmtime)
OUT = os.path.join(DIR, 'rosters.csv')
print(f"Using rosters file: {os.path.basename(XLSX)}")

# The 21 amateurs bundled into the all-or-nothing $0.25 Amateur Pod (from the entry sheet).
AMATEUR_POD = [
    "Jackson Koivun", "Preston Stout", "Ethan Fang", "Arni Sveinsson", "Ryder Cowan",
    "Miles Russell", "Mason Howell", "Eric Lee", "Logan Reilly", "Jackson Herrington",
    "Bryan Lee", "Mateo Pulcini", "Jackson Ormond", "Chase Kyes", "Matt Robles",
    "Marek Fleming", "Vaughn Harber", "Hamilton Coleman", "Brandon Holtz",
    "Guiseppe Puebla", "Jack Schoenberg",
]

df = pd.read_excel(XLSX, header=None)
print(f"Sheet shape: {df.shape}")

rows_out = []
# Scan every column for a participant header: a non-empty string whose next row down is "Name".
for col in range(df.shape[1]):
    for row in range(df.shape[0] - 1):
        val = df.iloc[row, col]
        next_val = df.iloc[row + 1, col]
        if (pd.notna(val) and isinstance(val, str) and val.strip()
                and pd.notna(next_val) and str(next_val).strip() == 'Name'):
            raw = val.strip()
            if raw.lower().startswith('us open pool') or raw.lower().startswith('u.s. open'):
                continue
            participant = raw
            price_col = col + 1
            r = row + 2
            while r < df.shape[0]:
                gval = df.iloc[r, col]
                if pd.notna(gval) and str(gval).strip() == 'TOTAL':
                    break
                if pd.notna(gval) and isinstance(gval, str) and gval.strip():
                    golfer_raw = gval.strip()
                    price_val = df.iloc[r, price_col] if price_col < df.shape[1] else None
                    try:
                        price = float(price_val)
                    except (ValueError, TypeError):
                        price = 0.0
                    # "Last, First" -> "First Last"; fix "Rai. Aaron" period typo
                    if '. ' in golfer_raw and ',' not in golfer_raw:
                        golfer_raw = golfer_raw.replace('. ', ', ', 1)
                    parts = golfer_raw.split(', ')
                    if len(parts) == 2:
                        golfer_name = f"{parts[1].strip()} {parts[0].strip()}"
                    else:
                        golfer_name = golfer_raw
                    golfer_name = golfer_name.replace('(a)', '').replace('*', '').strip()
                    rows_out.append({'Participant': participant, 'Golfer': golfer_name, 'Price': price})
                r += 1

# Expand the Amateur Pod into its 21 golfers (price split evenly so per-golfer prices sum to $0.25).
expanded = []
for r in rows_out:
    g = r['Golfer'].lower()
    if 'amateur pod' in g or g == 'amateur':
        for am in AMATEUR_POD:
            expanded.append({'Participant': r['Participant'], 'Golfer': am,
                             'Price': round(r['Price'] / len(AMATEUR_POD), 4)})
    else:
        expanded.append(r)

out_df = pd.DataFrame(expanded)
out_df.to_csv(OUT, index=False, encoding='utf-8')
print(f"Participants: {out_df['Participant'].nunique()}")
print(f"Total roster entries: {len(out_df)} (after Amateur Pod expansion)")
print(f"Saved: {OUT}\n")
for p in sorted(out_df['Participant'].unique()):
    sub = out_df[out_df['Participant'] == p]
    print(f"  {p}: {len(sub)} golfers, ${sub['Price'].sum():.2f}")
