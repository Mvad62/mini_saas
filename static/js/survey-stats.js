const chartColors = [
  "#3156c9",
  "#e17b35",
  "#32936f",
  "#bd4f70",
  "#8b65b5",
  "#c6a431",
  "#417f9d",
  "#d05b4b",
];

document.querySelectorAll("[data-chart-type]").forEach((canvas) => {
  if (typeof Chart === "undefined") {
    return;
  }

  const labels = JSON.parse(canvas.dataset.chartLabels);
  const values = JSON.parse(canvas.dataset.chartValues);
  const isPie = canvas.dataset.chartType === "pie";

  new Chart(canvas, {
    type: isPie ? "pie" : "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Количество ответов",
          data: values,
          backgroundColor: labels.map(
            (_, index) => chartColors[index % chartColors.length],
          ),
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: isPie ? "x" : "y",
      scales: isPie
        ? {}
        : {
            x: {
              beginAtZero: true,
              ticks: { precision: 0 },
            },
          },
      plugins: {
        legend: { display: isPie },
      },
    },
  });
});
