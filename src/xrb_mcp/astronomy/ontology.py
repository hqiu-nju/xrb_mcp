"""Versioned descriptive tags; never a replacement for physical quantities or classification."""

ONTOLOGY_VERSION = "0.1.0"
WAVELENGTHS = {
    "radio": ["radio", "GHz", "MHz", "MeerKAT", "VLA", "ATCA", "VLBI"],
    "infrared": ["infrared", "near-infrared", "mid-infrared"],
    "optical": ["optical", "photometry"],
    "ultraviolet": ["ultraviolet", "UVOT"],
    "xray": ["X-ray", "X ray", "X-rays", "NICER", "NuSTAR", "RXTE"],
    "gamma_ray": ["gamma-ray", "gamma ray", "Fermi"],
}
INSTRUMENTS = {
    "MeerKAT": ["MeerKAT"],
    "VLA": ["VLA", "JVLA", "Very Large Array"],
    "ATCA": ["ATCA", "Australia Telescope Compact Array"],
    "VLBA": ["VLBA", "Very Long Baseline Array"],
    "LOFAR": ["LOFAR"],
    "NICER": ["NICER"],
    "NuSTAR": ["NuSTAR"],
    "Swift": ["Swift"],
    "RXTE": ["RXTE"],
    "Chandra": ["Chandra"],
    "XMM-Newton": ["XMM-Newton"],
    "ALMA": ["ALMA"],
}
TOPICS = {
    "state_transition": ["state transition", "hard-to-soft", "soft-to-hard"],
    "jet_quenching": ["jet quenching", "quenched jet", "radio quenching"],
    "transient_ejecta": ["ejecta", "ejection"],
    "radio_xray_correlation": ["radio/X-ray correlation", "radio X-ray correlation"],
    "polarization": ["polarization", "polarisation"],
    "variability": ["variability", "variable"],
    "synchrotron_emission": ["synchrotron"],
    "accretion_state": ["hard state", "soft state", "intermediate state"],
}
