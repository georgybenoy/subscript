/**
 * Subscript Chart.js Visualization Engine
 * Dark luxury SaaS charts with purple/violet gradients & fallbacks
 */

// Global Chart.js styling defaults
if (window.Chart) {
  Chart.defaults.color = '#A1A1AA';
  Chart.defaults.font.family = "'Plus Jakarta Sans', sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.plugins.tooltip.backgroundColor = '#1D1D27';
  Chart.defaults.plugins.tooltip.titleColor = '#F5F3FF';
  Chart.defaults.plugins.tooltip.bodyColor = '#D4D4D8';
  Chart.defaults.plugins.tooltip.borderColor = '#30303B';
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 8;
  Chart.defaults.plugins.tooltip.boxPadding = 4;
}

/**
 * 1. Revenue Over Time (Line Chart with violet gradient fill)
 */
function initRevenueLineChart(canvasId, labels, dataValues) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  // Safe fallback if data is empty
  const defaultLabels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const defaultValues = [12000, 14500, 16800, 19200, 22400, 25100, 28300, 31000, 34200, 37500, 41200, 45000];

  const chartLabels = (labels && labels.length) ? labels : defaultLabels;
  const chartData = (dataValues && dataValues.length) ? dataValues : defaultValues;

  const chartContext = ctx.getContext('2d');
  const gradient = chartContext.createLinearGradient(0, 0, 0, 300);
  gradient.addColorStop(0, 'rgba(167, 139, 250, 0.45)');
  gradient.addColorStop(1, 'rgba(167, 139, 250, 0.0)');

  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: chartLabels,
      datasets: [{
        label: 'MRR Growth ($)',
        data: chartData,
        borderColor: '#A78BFA',
        borderWidth: 2.5,
        backgroundColor: gradient,
        tension: 0.38,
        fill: true,
        pointBackgroundColor: '#C084FC',
        pointBorderColor: '#101014',
        pointBorderWidth: 2,
        pointRadius: 4,
        pointHoverRadius: 6,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(context) {
              return ' $' + context.raw.toLocaleString();
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(255, 255, 255, 0.04)' },
          ticks: { color: '#828292' }
        },
        y: {
          grid: { color: 'rgba(255, 255, 255, 0.06)' },
          ticks: {
            color: '#828292',
            callback: function(val) { return '$' + (val >= 1000 ? (val / 1000) + 'k' : val); }
          }
        }
      }
    }
  });
}

/**
 * 2. Subscription Status Distribution (Doughnut Chart)
 */
function initSubscriptionDoughnutChart(canvasId, labels, dataValues) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const defaultLabels = ['Active', 'Quotation', 'Paused', 'Trialing', 'Closed'];
  const defaultValues = [64, 18, 8, 7, 3];

  const chartLabels = (labels && labels.length) ? labels : defaultLabels;
  const chartData = (dataValues && dataValues.length) ? dataValues : defaultValues;

  return new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: chartLabels,
      datasets: [{
        data: chartData,
        backgroundColor: [
          '#22C55E', // Active
          '#A78BFA', // Quotation
          '#F59E0B', // Paused
          '#38BDF8', // Trialing
          '#EF4444'  // Closed
        ],
        borderWidth: 3,
        borderColor: '#1D1D27',
        hoverOffset: 6
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '72%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            boxWidth: 12,
            boxHeight: 12,
            padding: 16,
            color: '#D4D4D8'
          }
        }
      }
    }
  });
}

/**
 * 3. Monthly Collections (Bar Chart)
 */
function initMonthlyCollectionsBarChart(canvasId, labels, dataValues) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const defaultLabels = ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'];
  const defaultValues = [18200, 21400, 24100, 26900, 31200, 35800];

  const chartLabels = (labels && labels.length) ? labels : defaultLabels;
  const chartData = (dataValues && dataValues.length) ? dataValues : defaultValues;

  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels: chartLabels,
      datasets: [{
        label: 'Collected ($)',
        data: chartData,
        backgroundColor: '#7C3AED',
        hoverBackgroundColor: '#8B5CF6',
        borderRadius: 6,
        borderSkipped: false,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(ctx) { return ' Collected: $' + ctx.raw.toLocaleString(); }
          }
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: '#828292' }
        },
        y: {
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: {
            color: '#828292',
            callback: function(val) { return '$' + (val >= 1000 ? (val / 1000) + 'k' : val); }
          }
        }
      }
    }
  });
}

/**
 * 4. Revenue Comparison Chart (Current Year vs Previous Year)
 */
function initRevenueComparisonChart(canvasId, labels, currentYear, lastYear) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const defaultLabels = ['Q1', 'Q2', 'Q3', 'Q4'];
  const defaultCurrent = [45000, 58000, 72000, 89000];
  const defaultLast = [32000, 39000, 48000, 55000];

  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels: (labels && labels.length) ? labels : defaultLabels,
      datasets: [
        {
          label: 'Current Year',
          data: (currentYear && currentYear.length) ? currentYear : defaultCurrent,
          backgroundColor: '#A78BFA',
          borderRadius: 6,
        },
        {
          label: 'Previous Year',
          data: (lastYear && lastYear.length) ? lastYear : defaultLast,
          backgroundColor: '#30303B',
          borderRadius: 6,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'top',
          labels: { boxWidth: 12, color: '#D4D4D8' }
        }
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#828292' } },
        y: {
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: {
            color: '#828292',
            callback: function(val) { return '$' + (val >= 1000 ? (val / 1000) + 'k' : val); }
          }
        }
      }
    }
  });
}
