"""Explicit ETL dependency graph, replacing the legacy flat `scripts/` folder.

Each entry's `depends_on` lists the stage names that must have produced
output before it can run. This makes the DAG inferred from the legacy
scripts (see docs/adr/0001-architecture.md addendum) executable and
checkable, instead of implicit in the order someone happens to run files in.

Stage modules live in app.ingestion.stages.<name> and expose a `run(...)`
function. Only `site_coordinates` is implemented so far (Phase 1, step 1);
the rest are registered here with their legacy source script noted so the
DAG shape is fixed before each stage is ported.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Stage:
    name: str
    legacy_script: str
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    implemented: bool = False


STAGES: tuple[Stage, ...] = (
    Stage("site_coordinates", "Capacity-Site-Coordinate-Process.py", implemented=True),
    Stage("site_coverage_params", "Capacity-Site-Coverage-Parameters.py", depends_on=("site_coordinates",)),
    Stage("xc_huawei", "xC Huawei Dataset.py", depends_on=("site_coordinates",)),
    Stage("xd_zte", "xD (ZTE Dataset).py", depends_on=("site_coordinates",)),
    Stage("congestion_analysis", "Capacity-Congestion-Analysis.py", depends_on=("xc_huawei", "xd_zte")),
    Stage("cd_combined_result", "Capacity-CD-Combined-Result.py", depends_on=("congestion_analysis",)),
    Stage("pre_capex_upgrades", "Pre-Capacity-CAPEX-Upgrades.py", depends_on=("congestion_analysis",)),
    Stage("capex_upgrades", "Capacity-CAPEX-Upgrades.py", depends_on=("pre_capex_upgrades",)),
    Stage("forecast_results", "Capacity-Forecast-Results.py", depends_on=("xc_huawei", "xd_zte")),
    Stage("coverage_holes", "Capacity-Coverage-Holes-Cluster-(DBSCAN).py"),
)


def topological_order() -> list[Stage]:
    by_name = {s.name: s for s in STAGES}
    visited: set[str] = set()
    order: list[Stage] = []

    def visit(stage: Stage) -> None:
        if stage.name in visited:
            return
        for dep in stage.depends_on:
            visit(by_name[dep])
        visited.add(stage.name)
        order.append(stage)

    for stage in STAGES:
        visit(stage)
    return order
