(() => {
    "use strict";

    const dataElement = document.getElementById("dashboard-chart-data");
    const ageCanvas = document.getElementById("age-group-chart");
    const foodCanvas = document.getElementById("food-security-chart");

    if (!dataElement || !ageCanvas || !foodCanvas || typeof Chart === "undefined") {
        return;
    }

    const dashboardData = JSON.parse(dataElement.textContent);
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const fontFamily = '"Segoe UI", "Helvetica Neue", Arial, sans-serif';

    Chart.defaults.font.family = fontFamily;
    Chart.defaults.color = "#5d6975";

    const sharedOptions = (unitLabel, horizontal = false) => ({
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: horizontal ? "y" : "x",
        animation: reduceMotion ? false : { duration: 320 },
        interaction: {
            intersect: false,
            mode: "nearest",
        },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: "#071a2f",
                titleColor: "#ffffff",
                bodyColor: "#ffffff",
                displayColors: false,
                padding: 11,
                callbacks: {
                    label(context) {
                        const value = horizontal ? context.parsed.x : context.parsed.y;
                        return `${unitLabel}: ${value.toLocaleString()}`;
                    },
                },
            },
        },
        scales: {
            x: {
                beginAtZero: true,
                grid: {
                    color: horizontal ? "#e5e9ed" : "transparent",
                    drawBorder: false,
                },
                ticks: {
                    color: "#5d6975",
                    precision: 0,
                },
                border: { display: false },
            },
            y: {
                beginAtZero: true,
                grid: {
                    color: horizontal ? "transparent" : "#e5e9ed",
                    drawBorder: false,
                },
                ticks: {
                    color: "#5d6975",
                    precision: 0,
                },
                border: { display: false },
            },
        },
    });

    new Chart(ageCanvas, {
        type: "bar",
        data: {
            labels: dashboardData.ageGroups.map((item) => item.label),
            datasets: [
                {
                    data: dashboardData.ageGroups.map((item) => item.value),
                    backgroundColor: ["#2e648f", "#15395f", "#c49a47"],
                    borderColor: ["#2e648f", "#15395f", "#a97e2f"],
                    borderWidth: 1,
                    borderRadius: 5,
                    borderSkipped: false,
                    maxBarThickness: 62,
                },
            ],
        },
        options: sharedOptions("Members"),
    });

    new Chart(foodCanvas, {
        type: "bar",
        data: {
            labels: dashboardData.foodSecurity.map((item) => item.label),
            datasets: [
                {
                    data: dashboardData.foodSecurity.map((item) => item.value),
                    backgroundColor: "#2e648f",
                    borderColor: "#214f74",
                    borderWidth: 1,
                    borderRadius: 5,
                    borderSkipped: false,
                    maxBarThickness: 34,
                },
            ],
        },
        options: sharedOptions("Households", true),
    });
})();
