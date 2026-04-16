const form = document.getElementById("route-form");
const sourceInput = document.getElementById("source");
const destinationInput = document.getElementById("destination");
const passengersInput = document.getElementById("passengers");
const predictButton = document.getElementById("predict-btn");

const statusBox = document.getElementById("status");
const resultCard = document.getElementById("result-card");
const optionsCard = document.getElementById("options-card");
const metaGrid = document.getElementById("meta-grid");

const sourceDisplay = document.getElementById("source-display");
const destinationDisplay = document.getElementById("destination-display");
const selectedMode = document.getElementById("selected-mode");
const climateLabel = document.getElementById("climate-label");
const bestRouteId = document.getElementById("best-route-id");
const bestRoutePath = document.getElementById("best-route-path");
const selectedReason = document.getElementById("selected-reason");
const publicTransportAssessment = document.getElementById("public-transport-assessment");
const optionsBody = document.getElementById("options-body");
const toolLog = document.getElementById("tool-log");
const memoryLog = document.getElementById("memory-log");

function showStatus(message, isError = false) {
  statusBox.textContent = message;
  statusBox.classList.remove("hidden");
  statusBox.style.color = isError ? "#ffd1d1" : "#d7e5ff";
  statusBox.style.borderColor = isError ? "rgba(255, 114, 114, 0.45)" : "rgba(167, 187, 255, 0.25)";
}

function clearResults() {
  optionsBody.innerHTML = "";
  toolLog.innerHTML = "";
  memoryLog.innerHTML = "";
}

function renderResult(data) {
  sourceDisplay.textContent = data.source_display;
  destinationDisplay.textContent = data.destination_display;
  selectedMode.textContent = data.selected_mode;
  climateLabel.textContent = data.climate_label;
  bestRouteId.textContent = data.best_route_id;
  bestRoutePath.textContent = data.best_route_path;
  selectedReason.textContent = data.selected_reason;
  publicTransportAssessment.textContent = data.public_transport_assessment;

  clearResults();
  data.all_options.forEach((item, idx) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${idx + 1}</td>
      <td>${item.mode}</td>
      <td>${item.duration_min.toFixed(2)}</td>
      <td>${item.distance_km.toFixed(2)}</td>
      <td>${item.score.toFixed(2)}</td>
    `;
    optionsBody.appendChild(tr);
  });

  data.tool_log.forEach((entry) => {
    const li = document.createElement("li");
    li.textContent = entry;
    toolLog.appendChild(li);
  });

  if (data.similar_memories.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No similar historical trips found.";
    memoryLog.appendChild(li);
  } else {
    data.similar_memories.forEach((entry) => {
      const li = document.createElement("li");
      li.textContent = `${entry.source} -> ${entry.destination} | mode=${entry.recommended_mode} | sim=${entry.score} | at=${entry.created_at}`;
      memoryLog.appendChild(li);
    });
  }

  resultCard.classList.remove("hidden");
  optionsCard.classList.remove("hidden");
  metaGrid.classList.remove("hidden");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const source = sourceInput.value.trim();
  const destination = destinationInput.value.trim();
  const passengers = Number.parseInt(passengersInput.value, 10);

  if (!source || !destination || !Number.isInteger(passengers) || passengers < 1) {
    showStatus("Please enter source, destination and valid passenger count.", true);
    return;
  }

  predictButton.disabled = true;
  predictButton.textContent = "Predicting...";
  showStatus("Running multi-agent route pipeline...");

  try {
    const response = await fetch("/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, destination, passengers }),
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Prediction failed.");
    }

    renderResult(data);
    showStatus("Prediction completed successfully.");
  } catch (error) {
    showStatus(`Error: ${error.message}`, true);
  } finally {
    predictButton.disabled = false;
    predictButton.textContent = "Predict Best Route";
  }
});
