ADMIN = "ADMIN"
WAREHOUSE = "WAREHOUSE"
LOGISTICS = "LOGISTICS"
VET = "VET"
OWNER = "OWNER"

ROLE_NAMES: dict[str, str] = {
    ADMIN: "Administrator",
    WAREHOUSE: "Omborchi",
    LOGISTICS: "Logistika xodimi",
    VET: "Veterinar",
    OWNER: "Xonadon egasi",
}

#: Web App bosh sahifasi rol bo'yicha (API_CONTRACT_V3 §15.1 ``homeFor``).
ROLE_HOME_PATHS: dict[str, str] = {
    ADMIN: "/dashboard",
    WAREHOUSE: "/dashboard",
    LOGISTICS: "/logistics",
    VET: "/vet",
    OWNER: "/my",
}


def home_path(role: str) -> str:
    return ROLE_HOME_PATHS.get(role, "/")


def role_name(role: str) -> str:
    return ROLE_NAMES.get(role, role)


def household_code(household_id: int) -> str:
    """Kontrakt bo'yicha xonadon kodi: ``XN-`` + 4 xonali ID."""
    return f"XN-{household_id:04d}"
