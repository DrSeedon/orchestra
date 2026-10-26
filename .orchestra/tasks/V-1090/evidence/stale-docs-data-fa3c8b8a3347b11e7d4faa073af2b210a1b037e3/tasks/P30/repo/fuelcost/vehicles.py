"""The cars of the pool and their fuel consumption."""
import csv
from decimal import Decimal, InvalidOperation

COLUMNS = ("car", "consumption")


def parseConsumption(text: str, where: str) -> Decimal:
    """Return a consumption in litres per 100 km; it must be above zero."""
    try:
        consumption = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"{where}: bad consumption {text!r}") from None
    if not consumption.is_finite() or consumption <= 0:
        raise ValueError(f"{where}: consumption must be above zero, got {text!r}")
    return consumption


def loadVehicles(path: str) -> dict[str, Decimal]:
    """Read the vehicles file and return the consumption of each car."""
    vehicles: dict[str, Decimal] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns {', '.join(missing)}")
        for lineNo, row in enumerate(reader, start=2):
            where = f"{path}:{lineNo}"
            car = (row["car"] or "").strip()
            if not car:
                raise ValueError(f"{where}: car is empty")
            if car in vehicles:
                raise ValueError(f"{where}: car {car} is listed twice")
            vehicles[car] = parseConsumption((row["consumption"] or "").strip(), where)
    return vehicles
