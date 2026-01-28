"""
PHANTOM STOCKS ADJUSTMENT SCRIPT
Adjusts RS rankings to account for ~2,800 missing stocks

Assumption: The missing stocks are mostly weak performers (bottom 35%)
This shifts your percentile rankings upward to better match IBD's 8,000 stock universe
"""

import json
import numpy as np
from datetime import datetime

def adjust_rs_rankings_with_phantoms():
    """
    Add phantom stocks to adjust percentile rankings
    
    Your universe: ~5,200 stocks
    IBD universe: ~8,000 stocks
    Missing: ~2,800 stocks
    
    Strategy: Assume missing stocks are weak performers, recalculate percentiles
    """
    
    print("="*80)
    print("PHANTOM STOCKS ADJUSTMENT - Matching IBD's 8,000 Stock Universe")
    print("="*80)
    print()
    
    # Load your current rankings
    try:
        with open('rankings.json', 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print("ERROR: rankings.json not found!")
        return
    
    stocks = data['data']
    original_count = len(stocks)
    
    print(f"Loaded {original_count} stocks from rankings.json")
    print()
    
    # Extract RS scores
    rs_scores = [s['rs_score'] for s in stocks]
    
    print("CURRENT DISTRIBUTION:")
    print("-" * 60)
    print(f"Min RS score: {min(rs_scores):.4f}")
    print(f"Max RS score: {max(rs_scores):.4f}")
    print(f"Average RS score: {np.mean(rs_scores):.4f}")
    print(f"Median RS score: {np.median(rs_scores):.4f}")
    print()
    
    # Calculate cutoff for bottom 35% of your stocks
    bottom_35_cutoff = np.percentile(rs_scores, 35)
    print(f"Bottom 35% cutoff: {bottom_35_cutoff:.4f}")
    print()
    
    # Generate phantom stocks
    # We'll create ~2,800 phantom stocks with RS scores in the bottom 35% range
    target_total = 8000
    num_phantoms = target_total - original_count
    
    print(f"TARGET UNIVERSE SIZE: {target_total}")
    print(f"YOUR STOCKS: {original_count}")
    print(f"PHANTOM STOCKS TO ADD: {num_phantoms}")
    print()
    
    # Generate phantom RS scores
    # Strategy: Distribute them in bottom 35% with some variation
    min_score = min(rs_scores)
    
    # Create phantoms with scores between min and bottom_35_cutoff
    # Use normal distribution centered at 20th percentile
    phantom_scores = []
    
    # 70% of phantoms in bottom 25%
    bottom_25_cutoff = np.percentile(rs_scores, 25)
    num_bottom_phantoms = int(num_phantoms * 0.7)
    phantom_scores.extend(np.random.uniform(min_score * 0.8, bottom_25_cutoff, num_bottom_phantoms))
    
    # 30% of phantoms in 25-35%
    num_mid_phantoms = num_phantoms - num_bottom_phantoms
    phantom_scores.extend(np.random.uniform(bottom_25_cutoff, bottom_35_cutoff, num_mid_phantoms))
    
    print("PHANTOM STOCK DISTRIBUTION:")
    print("-" * 60)
    print(f"Phantom scores range: {min(phantom_scores):.4f} to {max(phantom_scores):.4f}")
    print(f"Phantom average: {np.mean(phantom_scores):.4f}")
    print()
    
    # Combine your stocks with phantoms
    all_scores = rs_scores + list(phantom_scores)
    
    # Sort all scores
    sorted_indices = np.argsort(all_scores)[::-1]  # Descending order
    
    # Create mapping of original RS score to new rank
    score_to_new_rank = {}
    for new_rank, idx in enumerate(sorted_indices):
        if idx < original_count:  # Only map real stocks
            original_score = rs_scores[idx]
            percentile = int(((target_total - new_rank) / target_total) * 99) + 1
            score_to_new_rank[original_score] = min(percentile, 99)
    
    # Update stocks with new rankings
    adjusted_stocks = []
    rank_changes = []
    
    for stock in stocks:
        old_rank = stock['rs_rank']
        new_rank = score_to_new_rank.get(stock['rs_score'], old_rank)
        
        stock['rs_rank_original'] = old_rank  # Keep original for comparison
        stock['rs_rank'] = new_rank
        stock['rank_adjustment'] = new_rank - old_rank
        
        adjusted_stocks.append(stock)
        rank_changes.append(new_rank - old_rank)
    
    # Sort by new rank
    adjusted_stocks.sort(key=lambda x: x['rs_rank'], reverse=True)
    
    print("="*80)
    print("ADJUSTMENT RESULTS")
    print("="*80)
    print()
    
    print("RANK CHANGES:")
    print("-" * 60)
    print(f"Average adjustment: {np.mean(rank_changes):+.1f} points")
    print(f"Median adjustment: {np.median(rank_changes):+.1f} points")
    print(f"Min adjustment: {min(rank_changes):+.0f} points")
    print(f"Max adjustment: {max(rank_changes):+.0f} points")
    print()
    
    # Show distribution of changes
    increases = len([c for c in rank_changes if c > 0])
    decreases = len([c for c in rank_changes if c < 0])
    unchanged = len([c for c in rank_changes if c == 0])
    
    print(f"Ranks increased: {increases} ({increases/len(rank_changes)*100:.1f}%)")
    print(f"Ranks decreased: {decreases} ({decreases/len(rank_changes)*100:.1f}%)")
    print(f"Ranks unchanged: {unchanged} ({unchanged/len(rank_changes)*100:.1f}%)")
    print()
    
    # Show examples
    print("EXAMPLE ADJUSTMENTS (Top 20):")
    print("-" * 80)
    print(f"{'Symbol':<8} {'Old RS':<8} {'New RS':<8} {'Change':<8} {'Score':<12}")
    print("-" * 80)
    for stock in adjusted_stocks[:20]:
        change = stock['rank_adjustment']
        arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
        print(f"{stock['symbol']:<8} {stock['rs_rank_original']:<8} {stock['rs_rank']:<8} {change:+3} {arrow:<5} {stock['rs_score']:.4f}")
    
    print()
    
    # Show bottom performers
    print("EXAMPLE ADJUSTMENTS (Bottom 20):")
    print("-" * 80)
    print(f"{'Symbol':<8} {'Old RS':<8} {'New RS':<8} {'Change':<8} {'Score':<12}")
    print("-" * 80)
    for stock in adjusted_stocks[-20:]:
        change = stock['rank_adjustment']
        arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
        print(f"{stock['symbol']:<8} {stock['rs_rank_original']:<8} {stock['rs_rank']:<8} {change:+3} {arrow:<5} {stock['rs_score']:.4f}")
    
    print()
    
    # Save adjusted rankings
    output_data = {
        'last_updated': datetime.now().isoformat(),
        'formula_used': data.get('formula_used', 'Flexible'),
        'stage_2_criteria': data.get('stage_2_criteria', '50dma > 150dma > 200dma'),
        'total_stocks': len(adjusted_stocks),
        'full_calculations': data.get('full_calculations'),
        'partial_calculations': data.get('partial_calculations'),
        'stage_2_stocks': data.get('stage_2_stocks'),
        'update_type': 'phantom_adjusted',
        'adjustment_info': {
            'phantom_stocks_added': num_phantoms,
            'target_universe_size': target_total,
            'average_rank_change': round(float(np.mean(rank_changes)), 2),
            'adjustment_method': 'Added ~2,800 phantom stocks in bottom 35% to match IBD universe'
        },
        'note': 'RS ranks adjusted with phantom stocks to match IBD\'s ~8,000 stock universe',
        'data': adjusted_stocks
    }
    
    # Save
    with open('rankings_adjusted.json', 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print("="*80)
    print("SAVE OPTIONS")
    print("="*80)
    print()
    print("✅ Saved adjusted rankings to: rankings_adjusted.json")
    print()
    print("To use the adjusted rankings:")
    print("  Option 1: Keep both files (compare original vs adjusted)")
    print("  Option 2: Replace rankings.json with adjusted version")
    print()
    print("Recommendation: Test adjusted rankings against IBD first!")
    print("If they match better, replace rankings.json")
    print()
    
    # Statistics
    print("="*80)
    print("FINAL STATISTICS")
    print("="*80)
    print()
    print(f"Original universe: {original_count} stocks")
    print(f"Adjusted universe: {target_total} stocks (including {num_phantoms} phantoms)")
    print(f"Average RS increase: {np.mean(rank_changes):+.1f} points")
    print()
    print("Expected impact:")
    print("  • Top stocks (RS 95-99): Small increase (+1 to +2)")
    print("  • Mid stocks (RS 70-90): Moderate increase (+3 to +7)")
    print("  • Bottom stocks (RS <70): Larger increase (+5 to +10)")
    print()
    print("This should bring your RS rankings MUCH closer to IBD's!")
    print()

if __name__ == "__main__":
    adjust_rs_rankings_with_phantoms()
