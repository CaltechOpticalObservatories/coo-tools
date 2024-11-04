from cr_catalogue.cr_catalogue import cr_catalogue
from muon_fit.muon_detect import muon_detect

# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    zscore_limit = 2.7
    [mw0, mw1] = cr_catalogue("sample_data", zscore_limit)

    print(f'Spike found between {mw0} and {mw1}')
    
    # Detect muons in sample data
    muon_detect("sample_data", mw0, mw1, gplot=False, hplot=False, ps=True, crplot=False, verbose=False)
    