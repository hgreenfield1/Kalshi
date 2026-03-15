import re
from pathlib import Path

# MLB team mappings
mlb_teams = {
    "AZ": "Arizona Diamondbacks",
    "ARI": "Arizona Diamondbacks",
    "ATH": "Athletics",
    "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox",
    "CHC": "Chicago Cubs",
    "CWS": "Chicago White Sox",
    "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",
    "DET": "Detroit Tigers",
    "HOU": "Houston Astros",
    "KC":  "Kansas City Royals",
    "LAA": "Los Angeles Angels",
    "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",
    "NYM": "New York Mets",
    "NYY": "New York Yankees",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "SD":  "San Diego Padres",
    "SEA": "Seattle Mariners",
    "SF":  "San Francisco Giants",
    "STL": "St. Louis Cardinals",
    "TB":  "Tampa Bay Rays",
    "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",
    "WSH": "Washington Nationals"
}

# Win probability lookup file path
WIN_PROBS_FILE = Path(__file__).parent / 'win_probs.txt'

def getProbability(homeOrVisitor, inning, outs, runners, scoreDiff):
    """Get win probability from lookup table."""
    return getProbabilityOfString('"%s",%d,%d,%d,%d' % (homeOrVisitor, inning, outs, runners, scoreDiff))

def getProbabilityOfString(stringToLookFor):
    """Look up win probability from file."""
    probsRe = re.compile(r'^%s,(\d+),(\d+)' % (stringToLookFor))
    probsFile = open(WIN_PROBS_FILE, 'r')
    for line in probsFile.readlines():
        if (line.startswith(stringToLookFor)):
            probsMatch = probsRe.match(line)
            if (probsMatch):
                totalGames = int(probsMatch.group(1))
                winGames = int(probsMatch.group(2))
                probsFile.close()
                return float(winGames)/float(totalGames)
            else:
                print("ERROR - inconsistent re!")
    probsFile.close()
    return -1
