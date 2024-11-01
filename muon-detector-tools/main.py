from muon_fit.muon_fit import muon_fit
from cr_catalogue.cr_catalogue import cr_catalogue

# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    # Run muon_fit with sample data
    muon_fit("sample_data", 0.45, 0.69, gplot=False, hplot=False, ps=True, crplot=False, verbose=False)
    # cr_catalogue("muon_data")