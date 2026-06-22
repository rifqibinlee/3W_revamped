from app.ingestion.dag import topological_order


def test_dependencies_run_before_dependents() -> None:
    order = topological_order()
    position = {stage.name: i for i, stage in enumerate(order)}

    for stage in order:
        for dep in stage.depends_on:
            assert position[dep] < position[stage.name]
