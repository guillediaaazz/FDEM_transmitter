#pragma once

#include <cmath>
#include <cstddef>

namespace OffsetGainMath {
struct LinearFit {
  bool valid = false;
  float slope = 0.0f;
  float intercept = 0.0f;
  float rmse = 0.0f;
};

inline LinearFit fitLine(const float* x, const float* y, std::size_t count) {
  LinearFit fit;
  if (x == nullptr || y == nullptr || count < 2) return fit;

  float sumX = 0.0f;
  float sumY = 0.0f;
  float sumXX = 0.0f;
  float sumXY = 0.0f;
  for (std::size_t index = 0; index < count; ++index) {
    if (!std::isfinite(x[index]) || !std::isfinite(y[index])) return fit;
    sumX += x[index];
    sumY += y[index];
    sumXX += x[index] * x[index];
    sumXY += x[index] * y[index];
  }
  const float denominator = count * sumXX - sumX * sumX;
  if (std::fabs(denominator) < 1.0e-9f) return fit;

  fit.slope = (count * sumXY - sumX * sumY) / denominator;
  fit.intercept = (sumY - fit.slope * sumX) / count;
  float squaredError = 0.0f;
  for (std::size_t index = 0; index < count; ++index) {
    const float residual = y[index] - (fit.intercept + fit.slope * x[index]);
    squaredError += residual * residual;
  }
  fit.rmse = std::sqrt(squaredError / count);
  fit.valid = std::isfinite(fit.slope) && std::isfinite(fit.intercept) && std::isfinite(fit.rmse);
  return fit;
}

inline bool deriveGainScale(float currentScale, float sweepSlope, float dacResponseSlope,
                            float minimumDacResponse, float minimumScale, float maximumScale,
                            float& calculatedScale) {
  if (!std::isfinite(currentScale) || !std::isfinite(sweepSlope) || !std::isfinite(dacResponseSlope) ||
      std::fabs(dacResponseSlope) < minimumDacResponse) {
    return false;
  }
  calculatedScale = currentScale - sweepSlope / dacResponseSlope;
  return std::isfinite(calculatedScale) && calculatedScale >= minimumScale && calculatedScale <= maximumScale;
}
}  // namespace OffsetGainMath
