"""Public package interface with lazy imports."""

__all__ = [
    "BikeshareSimulator",
    "SimulatorConfig",
    "create_fastapi_app",
    "STATION_META",
    "calculate_station_spc",
    "generate_dmaic_report",
]


def __getattr__(name):
    if name in ("BikeshareSimulator", "SimulatorConfig", "create_fastapi_app", "STATION_META"):
        from . import bikeshare_simulator
        return getattr(bikeshare_simulator, name)
    if name in ("calculate_station_spc", "generate_dmaic_report"):
        from . import spc_analytics
        return getattr(spc_analytics, name)
    raise AttributeError(name)
