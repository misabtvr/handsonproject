from __future__ import annotations

from app.pipeline import RoutePredictorPipeline


def print_result(output) -> None:
    print("\n=== Route Predictor Result ===")
    print(f"Source      : {output.source_display}")
    print(f"Destination : {output.destination_display}")
    print(f"Best Mode   : {output.selected_mode}")
    print(f"Climate     : {output.climate_label}")
    print(f"Best Route ID : {output.best_route_id}")
    print(f"Best Route    : {output.best_route_path}")
    print(f"Reason      : {output.selected_reason}")
    print(f"Public Transport Check : {output.public_transport_assessment}")

    print("\nRanked Options:")
    for rank, option in enumerate(output.all_options, start=1):
        print(
            f"  {rank}. {option.mode:<17}"
            f" ETA={option.duration_min:>7.1f} min |"
            f" Distance={option.distance_km:>6.2f} km |"
            f" Score={option.score:>7.2f}"
        )

    print("\nTool Calls:")
    for item in output.tool_log:
        print(f"  - {item}")

    print("\nMemory Matches:")
    if not output.similar_memories:
        print("  - No similar historical trips found.")
    else:
        for mem in output.similar_memories:
            print(
                f"  - {mem.source} -> {mem.destination} | mode={mem.recommended_mode} |"
                f" sim={mem.score:.2f} | at={mem.created_at}"
            )


def main() -> None:
    pipeline = RoutePredictorPipeline()

    print("Route Predictor Agentic CLI")
    print("Type 'exit' to quit.\n")
    while True:
        source = input("Enter Source: ").strip()
        if source.lower() == "exit":
            break
        destination = input("Enter Destination: ").strip()
        if destination.lower() == "exit":
            break
        if not source or not destination:
            print("Source and destination are required.\n")
            continue
        passengers_raw = input("Number of passengers (default 1): ").strip() or "1"
        try:
            passengers = int(passengers_raw)
            if passengers < 1:
                raise ValueError("Passenger count must be >= 1")
        except ValueError:
            print("Invalid passenger count.\n")
            continue

        try:
            result = pipeline.run(source, destination, passengers=passengers)
            print_result(result)
        except Exception as exc:
            print(f"Error: {exc}")
        print()


if __name__ == "__main__":
    main()
