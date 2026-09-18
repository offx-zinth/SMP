"""Comprehensive unit tests for vector math operations."""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if len(vec_a) != len(vec_b):
        raise ValueError("Vectors must have the same dimension")
    if not vec_a or not vec_b:
        raise ValueError("Vectors cannot be empty")
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def normalize_vector(vec: list[float]) -> list[float]:
    if not vec:
        raise ValueError("Vector cannot be empty")
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return [0.0] * len(vec)
    return [v / norm for v in vec]


def euclidean_distance(vec_a: list[float], vec_b: list[float]) -> float:
    if len(vec_a) != len(vec_b):
        raise ValueError("Vectors must have the same dimension")
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(vec_a, vec_b, strict=True)))


def manhattan_distance(vec_a: list[float], vec_b: list[float]) -> float:
    if len(vec_a) != len(vec_b):
        raise ValueError("Vectors must have the same dimension")
    return sum(abs(a - b) for a, b in zip(vec_a, vec_b, strict=True))


def chebyshev_distance(vec_a: list[float], vec_b: list[float]) -> float:
    if len(vec_a) != len(vec_b):
        raise ValueError("Vectors must have the same dimension")
    return float(max(abs(a - b) for a, b in zip(vec_a, vec_b, strict=True)))


def minkowski_distance(vec_a: list[float], vec_b: list[float], p: float = 2.0) -> float:
    if len(vec_a) != len(vec_b):
        raise ValueError("Vectors must have the same dimension")
    if p <= 0:
        raise ValueError("p must be positive")
    power_sum = sum(abs(a - b) ** p for a, b in zip(vec_a, vec_b, strict=True))
    return float(power_sum ** (1.0 / p))


def vector_add(vec_a: list[float], vec_b: list[float]) -> list[float]:
    if len(vec_a) != len(vec_b):
        raise ValueError("Vectors must have the same dimension")
    return [a + b for a, b in zip(vec_a, vec_b, strict=True)]


def vector_subtract(vec_a: list[float], vec_b: list[float]) -> list[float]:
    if len(vec_a) != len(vec_b):
        raise ValueError("Vectors must have the same dimension")
    return [a - b for a, b in zip(vec_a, vec_b, strict=True)]


def dot_product(vec_a: list[float], vec_b: list[float]) -> float:
    if len(vec_a) != len(vec_b):
        raise ValueError("Vectors must have the same dimension")
    return sum(a * b for a, b in zip(vec_a, vec_b, strict=True))


def magnitude(vec: list[float]) -> float:
    if not vec:
        raise ValueError("Vector cannot be empty")
    return math.sqrt(sum(v * v for v in vec))


def vector_multiply_scalar(vec: list[float], scalar: float) -> list[float]:
    return [v * scalar for v in vec]


def vector_divide_scalar(vec: list[float], scalar: float) -> list[float]:
    if scalar == 0:
        raise ValueError("Cannot divide by zero")
    return [v / scalar for v in vec]


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        vec = [1.0, 2.0, 3.0]
        result = cosine_similarity(vec, vec)
        assert result == pytest.approx(1.0)

    def test_opposite_vectors(self) -> None:
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [-1.0, 0.0, 0.0]
        result = cosine_similarity(vec_a, vec_b)
        assert result == pytest.approx(-1.0)

    def test_orthogonal_vectors(self) -> None:
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.0, 1.0, 0.0]
        result = cosine_similarity(vec_a, vec_b)
        assert result == pytest.approx(0.0)

    def test_partial_similarity(self) -> None:
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [2.0, 4.0, 6.0]
        result = cosine_similarity(vec_a, vec_b)
        assert result == pytest.approx(1.0)

    def test_three_dimensional_vectors(self) -> None:
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [4.0, 5.0, 6.0]
        result = cosine_similarity(vec_a, vec_b)
        expected = (1 * 4 + 2 * 5 + 3 * 6) / (math.sqrt(14) * math.sqrt(77))
        assert result == pytest.approx(expected)

    def test_dimension_mismatch_raises(self) -> None:
        vec_a = [1.0, 2.0]
        vec_b = [1.0, 2.0, 3.0]
        with pytest.raises(ValueError, match="same dimension"):
            cosine_similarity(vec_a, vec_b)

    def test_empty_vector_raises(self) -> None:
        with pytest.raises(ValueError, match="same dimension|cannot be empty"):
            cosine_similarity([], [])

    def test_zero_vector_a(self) -> None:
        vec_a = [0.0, 0.0, 0.0]
        vec_b = [1.0, 2.0, 3.0]
        result = cosine_similarity(vec_a, vec_b)
        assert result == 0.0

    def test_zero_vector_b(self) -> None:
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [0.0, 0.0, 0.0]
        result = cosine_similarity(vec_a, vec_b)
        assert result == 0.0

    def test_both_zero_vectors(self) -> None:
        vec_a = [0.0, 0.0, 0.0]
        vec_b = [0.0, 0.0, 0.0]
        result = cosine_similarity(vec_a, vec_b)
        assert result == 0.0


class TestVectorNormalization:
    def test_unit_vector(self) -> None:
        vec = [3.0, 4.0]
        result = normalize_vector(vec)
        assert result == pytest.approx([0.6, 0.8])
        assert magnitude(result) == pytest.approx(1.0)

    def test_normalize_preserves_direction(self) -> None:
        vec = [1.0, 1.0, 1.0]
        result = normalize_vector(vec)
        norm = magnitude(result)
        assert norm == pytest.approx(1.0)
        assert all(v == result[0] for v in result)

    def test_zero_vector_returns_zeros(self) -> None:
        vec = [0.0, 0.0, 0.0]
        result = normalize_vector(vec)
        assert result == [0.0, 0.0, 0.0]

    def test_negative_vector(self) -> None:
        vec = [-3.0, -4.0]
        result = normalize_vector(vec)
        assert result == pytest.approx([-0.6, -0.8])

    def test_mixed_sign_vector(self) -> None:
        vec = [1.0, -2.0, 3.0]
        result = normalize_vector(vec)
        expected_norm = magnitude(vec)
        assert all(abs(v) / expected_norm == pytest.approx(abs(r)) for v, r in zip(vec, result, strict=True))

    def test_empty_vector_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            normalize_vector([])

    def test_single_element(self) -> None:
        vec = [5.0]
        result = normalize_vector(vec)
        assert result == [1.0]

    def test_high_dimensional_vector(self) -> None:
        vec = [1.0] * 100
        result = normalize_vector(vec)
        assert magnitude(result) == pytest.approx(1.0)


class TestEuclideanDistance:
    def test_same_point(self) -> None:
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [1.0, 2.0, 3.0]
        result = euclidean_distance(vec_a, vec_b)
        assert result == pytest.approx(0.0)

    def test_simple_distance(self) -> None:
        vec_a = [0.0, 0.0]
        vec_b = [3.0, 4.0]
        result = euclidean_distance(vec_a, vec_b)
        assert result == pytest.approx(5.0)

    def test_negative_coordinates(self) -> None:
        vec_a = [-1.0, -2.0]
        vec_b = [1.0, 2.0]
        result = euclidean_distance(vec_a, vec_b)
        assert result == pytest.approx(math.sqrt(20))

    def test_dimension_mismatch_raises(self) -> None:
        vec_a = [1.0, 2.0]
        vec_b = [1.0, 2.0, 3.0]
        with pytest.raises(ValueError, match="same dimension"):
            euclidean_distance(vec_a, vec_b)

    def test_large_values(self) -> None:
        vec_a = [1e10, 1e10]
        vec_b = [0.0, 0.0]
        result = euclidean_distance(vec_a, vec_b)
        expected = math.sqrt(2 * (1e10) ** 2)
        assert result == pytest.approx(expected)

    def test_small_values(self) -> None:
        vec_a = [1e-10, 1e-10]
        vec_b = [0.0, 0.0]
        result = euclidean_distance(vec_a, vec_b)
        assert result == pytest.approx(math.sqrt(2) * 1e-10)


class TestManhattanDistance:
    def test_same_point(self) -> None:
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [1.0, 2.0, 3.0]
        result = manhattan_distance(vec_a, vec_b)
        assert result == pytest.approx(0.0)

    def test_simple_distance(self) -> None:
        vec_a = [0.0, 0.0]
        vec_b = [3.0, 4.0]
        result = manhattan_distance(vec_a, vec_b)
        assert result == pytest.approx(7.0)

    def test_negative_coordinates(self) -> None:
        vec_a = [-1.0, -2.0]
        vec_b = [1.0, 2.0]
        result = manhattan_distance(vec_a, vec_b)
        assert result == pytest.approx(6.0)

    def test_dimension_mismatch_raises(self) -> None:
        vec_a = [1.0, 2.0]
        vec_b = [1.0, 2.0, 3.0]
        with pytest.raises(ValueError, match="same dimension"):
            manhattan_distance(vec_a, vec_b)

    def test_one_dimensional(self) -> None:
        vec_a = [5.0]
        vec_b = [-3.0]
        result = manhattan_distance(vec_a, vec_b)
        assert result == pytest.approx(8.0)


class TestChebyshevDistance:
    def test_same_point(self) -> None:
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [1.0, 2.0, 3.0]
        result = chebyshev_distance(vec_a, vec_b)
        assert result == pytest.approx(0.0)

    def test_single_dimension(self) -> None:
        vec_a = [0.0]
        vec_b = [5.0]
        result = chebyshev_distance(vec_a, vec_b)
        assert result == pytest.approx(5.0)

    def test_multiple_dimensions_takes_max(self) -> None:
        vec_a = [0.0, 0.0]
        vec_b = [3.0, 4.0]
        result = chebyshev_distance(vec_a, vec_b)
        assert result == pytest.approx(4.0)

    def test_negative_coordinates(self) -> None:
        vec_a = [-10.0, 5.0]
        vec_b = [2.0, -3.0]
        result = chebyshev_distance(vec_a, vec_b)
        assert result == pytest.approx(12.0)

    def test_dimension_mismatch_raises(self) -> None:
        vec_a = [1.0, 2.0]
        vec_b = [1.0, 2.0, 3.0]
        with pytest.raises(ValueError, match="same dimension"):
            chebyshev_distance(vec_a, vec_b)


class TestMinkowskiDistance:
    def test_p_equals_2_is_euclidean(self) -> None:
        vec_a = [0.0, 0.0]
        vec_b = [3.0, 4.0]
        result = minkowski_distance(vec_a, vec_b, p=2.0)
        assert result == pytest.approx(5.0)

    def test_p_equals_1_is_manhattan(self) -> None:
        vec_a = [0.0, 0.0]
        vec_b = [3.0, 4.0]
        result = minkowski_distance(vec_a, vec_b, p=1.0)
        assert result == pytest.approx(7.0)

    def test_p_equals_infinity_is_chebyshev(self) -> None:
        vec_a = [0.0, 0.0]
        vec_b = [3.0, 4.0]
        result = minkowski_distance(vec_a, vec_b, p=100.0)
        assert result == pytest.approx(4.0)

    def test_invalid_p_raises(self) -> None:
        vec_a = [1.0, 2.0]
        vec_b = [1.0, 2.0]
        with pytest.raises(ValueError, match="p must be positive"):
            minkowski_distance(vec_a, vec_b, p=0.0)
        with pytest.raises(ValueError, match="p must be positive"):
            minkowski_distance(vec_a, vec_b, p=-1.0)


class TestVectorAddition:
    def test_simple_addition(self) -> None:
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [4.0, 5.0, 6.0]
        result = vector_add(vec_a, vec_b)
        assert result == [5.0, 7.0, 9.0]

    def test_with_negative_values(self) -> None:
        vec_a = [1.0, -2.0, 3.0]
        vec_b = [-4.0, 5.0, -6.0]
        result = vector_add(vec_a, vec_b)
        assert result == [-3.0, 3.0, -3.0]

    def test_with_zeros(self) -> None:
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [0.0, 0.0, 0.0]
        result = vector_add(vec_a, vec_b)
        assert result == [1.0, 2.0, 3.0]

    def test_dimension_mismatch_raises(self) -> None:
        vec_a = [1.0, 2.0]
        vec_b = [1.0, 2.0, 3.0]
        with pytest.raises(ValueError, match="same dimension"):
            vector_add(vec_a, vec_b)

    def test_result_magnitude(self) -> None:
        vec_a = [3.0, 4.0]
        vec_b = [1.0, 2.0]
        result = vector_add(vec_a, vec_b)
        assert magnitude(result) == pytest.approx(magnitude([4.0, 6.0]))


class TestVectorSubtraction:
    def test_simple_subtraction(self) -> None:
        vec_a = [5.0, 7.0, 9.0]
        vec_b = [4.0, 5.0, 6.0]
        result = vector_subtract(vec_a, vec_b)
        assert result == [1.0, 2.0, 3.0]

    def test_with_negative_values(self) -> None:
        vec_a = [1.0, -2.0, 3.0]
        vec_b = [4.0, -5.0, 6.0]
        result = vector_subtract(vec_a, vec_b)
        assert result == [-3.0, 3.0, -3.0]

    def test_result_is_zero_when_equal(self) -> None:
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [1.0, 2.0, 3.0]
        result = vector_subtract(vec_a, vec_b)
        assert result == [0.0, 0.0, 0.0]

    def test_dimension_mismatch_raises(self) -> None:
        vec_a = [1.0, 2.0]
        vec_b = [1.0, 2.0, 3.0]
        with pytest.raises(ValueError, match="same dimension"):
            vector_subtract(vec_a, vec_b)


class TestDotProduct:
    def test_simple_dot_product(self) -> None:
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [4.0, 5.0, 6.0]
        result = dot_product(vec_a, vec_b)
        assert result == pytest.approx(32.0)

    def test_orthogonal_vectors(self) -> None:
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.0, 1.0, 0.0]
        result = dot_product(vec_a, vec_b)
        assert result == pytest.approx(0.0)

    def test_identical_unit_vectors(self) -> None:
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [1.0, 0.0, 0.0]
        result = dot_product(vec_a, vec_b)
        assert result == pytest.approx(1.0)

    def test_with_negative_values(self) -> None:
        vec_a = [1.0, -2.0, 3.0]
        vec_b = [-4.0, 5.0, -6.0]
        result = dot_product(vec_a, vec_b)
        assert result == pytest.approx(-32.0)

    def test_dimension_mismatch_raises(self) -> None:
        vec_a = [1.0, 2.0]
        vec_b = [1.0, 2.0, 3.0]
        with pytest.raises(ValueError, match="same dimension"):
            dot_product(vec_a, vec_b)

    def test_single_dimension(self) -> None:
        vec_a = [5.0]
        vec_b = [3.0]
        result = dot_product(vec_a, vec_b)
        assert result == pytest.approx(15.0)


class TestMagnitude:
    def test_simple_magnitude(self) -> None:
        vec = [3.0, 4.0]
        result = magnitude(vec)
        assert result == pytest.approx(5.0)

    def test_three_dimensional(self) -> None:
        vec = [1.0, 2.0, 2.0]
        result = magnitude(vec)
        assert result == pytest.approx(3.0)

    def test_zero_vector(self) -> None:
        vec = [0.0, 0.0, 0.0]
        result = magnitude(vec)
        assert result == pytest.approx(0.0)

    def test_negative_values(self) -> None:
        vec = [-3.0, -4.0]
        result = magnitude(vec)
        assert result == pytest.approx(5.0)

    def test_empty_vector_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            magnitude([])

    def test_single_element(self) -> None:
        vec = [5.0]
        result = magnitude(vec)
        assert result == pytest.approx(5.0)


class TestVectorScalarOperations:
    def test_multiply_scalar(self) -> None:
        vec = [1.0, 2.0, 3.0]
        result = vector_multiply_scalar(vec, 2.0)
        assert result == [2.0, 4.0, 6.0]

    def test_multiply_by_zero(self) -> None:
        vec = [1.0, 2.0, 3.0]
        result = vector_multiply_scalar(vec, 0.0)
        assert result == [0.0, 0.0, 0.0]

    def test_multiply_by_negative(self) -> None:
        vec = [1.0, 2.0, 3.0]
        result = vector_multiply_scalar(vec, -2.0)
        assert result == [-2.0, -4.0, -6.0]

    def test_divide_scalar(self) -> None:
        vec = [2.0, 4.0, 6.0]
        result = vector_divide_scalar(vec, 2.0)
        assert result == [1.0, 2.0, 3.0]

    def test_divide_by_zero_raises(self) -> None:
        vec = [1.0, 2.0, 3.0]
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            vector_divide_scalar(vec, 0.0)


class TestArrayTypeHandling:
    def test_numpy_array_input(self) -> None:
        vec_a = np.array([1.0, 2.0, 3.0])
        vec_b = np.array([4.0, 5.0, 6.0])
        result = cosine_similarity(vec_a.tolist(), vec_b.tolist())
        expected = (1 * 4 + 2 * 5 + 3 * 6) / (math.sqrt(14) * math.sqrt(77))
        assert result == pytest.approx(expected)

    def test_list_input(self) -> None:
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [4.0, 5.0, 6.0]
        result = cosine_similarity(vec_a, vec_b)
        expected = (1 * 4 + 2 * 5 + 3 * 6) / (math.sqrt(14) * math.sqrt(77))
        assert result == pytest.approx(expected)

    def test_mixed_numpy_and_list(self) -> None:
        vec_a = np.array([1.0, 2.0, 3.0])
        vec_b = [4.0, 5.0, 6.0]
        result = cosine_similarity(vec_a.tolist(), vec_b)
        expected = (1 * 4 + 2 * 5 + 3 * 6) / (math.sqrt(14) * math.sqrt(77))
        assert result == pytest.approx(expected)

    def test_normalize_with_numpy_array(self) -> None:
        vec = np.array([3.0, 4.0])
        result = normalize_vector(vec.tolist())
        assert result == pytest.approx([0.6, 0.8])

    def test_euclidean_with_numpy_array(self) -> None:
        vec_a = np.array([0.0, 0.0])
        vec_b = np.array([3.0, 4.0])
        result = euclidean_distance(vec_a.tolist(), vec_b.tolist())
        assert result == pytest.approx(5.0)


class TestEdgeCases:
    def test_very_large_values(self) -> None:
        vec_a = [1e100, 1e100]
        vec_b = [0.0, 0.0]
        result = euclidean_distance(vec_a, vec_b)
        expected = math.sqrt(2 * (1e100) ** 2)
        assert result == pytest.approx(expected)

    def test_very_small_values(self) -> None:
        vec_a = [1e-100, 1e-100]
        vec_b = [0.0, 0.0]
        result = euclidean_distance(vec_a, vec_b)
        expected = math.sqrt(2) * 1e-100
        assert result == pytest.approx(expected)

    def test_all_negative_vectors(self) -> None:
        vec_a = [-1.0, -2.0, -3.0]
        vec_b = [-4.0, -5.0, -6.0]
        result = cosine_similarity(vec_a, vec_b)
        expected = (1 * 4 + 2 * 5 + 3 * 6) / (math.sqrt(14) * math.sqrt(77))
        assert result == pytest.approx(expected)

    def test_high_dimensional_vectors(self) -> None:
        vec_a = [1.0] * 1000
        vec_b = [2.0] * 1000
        result = cosine_similarity(vec_a, vec_b)
        assert result == pytest.approx(1.0)

    def test_sparse_vectors(self) -> None:
        vec_a = [0.0, 0.0, 0.0, 1.0, 0.0]
        vec_b = [0.0, 1.0, 0.0, 0.0, 0.0]
        result = cosine_similarity(vec_a, vec_b)
        assert result == pytest.approx(0.0)

    def test_mixed_large_and_small(self) -> None:
        vec_a = [1e10, 1e-10]
        vec_b = [0.0, 0.0]
        result = euclidean_distance(vec_a, vec_b)
        expected = math.sqrt((1e10) ** 2 + (1e-10) ** 2)
        assert result == pytest.approx(expected)


class TestWithMocking:
    def test_cosine_similarity_with_mocked_math(self) -> None:
        with patch("tests.unit.test_vector_math.math.sqrt") as mock_sqrt:
            mock_sqrt.return_value = 5.0
            vec = [3.0, 4.0]
            result = magnitude(vec)
            assert result == 5.0

    def test_normalize_with_mocked_math(self) -> None:
        with patch("tests.unit.test_vector_math.math.sqrt") as mock_sqrt:
            mock_sqrt.return_value = 1.0
            vec = [1.0, 1.0]
            result = normalize_vector(vec)
            assert result == [1.0, 1.0]

    def test_distance_with_mocked_calculation(self) -> None:
        mock_math = MagicMock()
        mock_math.sqrt.return_value = 5.0
        with patch.object(math, "sqrt", mock_math.sqrt):
            vec_a = [0.0, 0.0]
            vec_b = [3.0, 4.0]
            result = euclidean_distance(vec_a, vec_b)
            assert result == 5.0

    def test_dot_product_with_mocked_sum(self) -> None:
        mock_sum = MagicMock(return_value=32.0)
        with patch("tests.unit.test_vector_math.sum", mock_sum):
            vec_a = [1.0, 2.0, 3.0]
            vec_b = [4.0, 5.0, 6.0]
            result = dot_product(vec_a, vec_b)
            assert result == 32.0

    def test_vector_add_with_mocked_zip(self) -> None:
        vec_a = [1.0, 2.0]
        vec_b = [3.0, 4.0]
        result = vector_add(vec_a, vec_b)
        assert result == [4.0, 6.0]

    def test_cosine_with_mocked_numpy(self) -> None:
        mock_np = MagicMock()
        mock_np.linalg.norm.return_value = 5.0
        with patch("tests.unit.test_vector_math.np", mock_np):
            vec = [3.0, 4.0]
            result = magnitude(vec)
            assert result == 5.0

    def test_manhattan_with_mocked_abs(self) -> None:
        mock_abs = MagicMock(side_effect=lambda x: abs(x))
        with patch("tests.unit.test_vector_math.abs", mock_abs):
            vec_a = [1.0, -2.0]
            vec_b = [-1.0, 2.0]
            result = manhattan_distance(vec_a, vec_b)
            assert result == 6.0


class TestNumpyIntegration:
    def test_numpy_cosine_similarity(self) -> None:
        vec_a = np.array([1.0, 2.0, 3.0])
        vec_b = np.array([4.0, 5.0, 6.0])
        dot = np.dot(vec_a, vec_b)
        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)
        expected = dot / (norm_a * norm_b)
        result = cosine_similarity(vec_a.tolist(), vec_b.tolist())
        assert result == pytest.approx(expected)

    def test_numpy_normalization(self) -> None:
        vec = np.array([3.0, 4.0])
        normalized = vec / np.linalg.norm(vec)
        result = normalize_vector(vec.tolist())
        assert result == pytest.approx(normalized.tolist())

    def test_numpy_euclidean(self) -> None:
        vec_a = np.array([0.0, 0.0])
        vec_b = np.array([3.0, 4.0])
        expected = np.linalg.norm(vec_a - vec_b)
        result = euclidean_distance(vec_a.tolist(), vec_b.tolist())
        assert result == pytest.approx(expected)

    def test_numpy_manhattan(self) -> None:
        vec_a = np.array([1.0, 2.0, 3.0])
        vec_b = np.array([4.0, 5.0, 6.0])
        expected = np.sum(np.abs(vec_a - vec_b))
        result = manhattan_distance(vec_a.tolist(), vec_b.tolist())
        assert result == pytest.approx(expected)

    def test_numpy_dot_product(self) -> None:
        vec_a = np.array([1.0, 2.0, 3.0])
        vec_b = np.array([4.0, 5.0, 6.0])
        expected = np.dot(vec_a, vec_b)
        result = dot_product(vec_a.tolist(), vec_b.tolist())
        assert result == pytest.approx(expected)

    def test_numpy_magnitude(self) -> None:
        vec = np.array([3.0, 4.0])
        expected = np.linalg.norm(vec)
        result = magnitude(vec.tolist())
        assert result == pytest.approx(expected)


class TestConsistencyAcrossOperations:
    def test_cosine_similarity_consistency_with_normalization(self) -> None:
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [4.0, 5.0, 6.0]
        norm_a = normalize_vector(vec_a)
        norm_b = normalize_vector(vec_b)
        dot = dot_product(norm_a, norm_b)
        cos_sim = cosine_similarity(vec_a, vec_b)
        assert cos_sim == pytest.approx(dot)

    def test_euclidean_from_minkowski(self) -> None:
        vec_a = [0.0, 0.0]
        vec_b = [3.0, 4.0]
        euclid = euclidean_distance(vec_a, vec_b)
        mink = minkowski_distance(vec_a, vec_b, p=2.0)
        assert euclid == pytest.approx(mink)

    def test_manhattan_from_minkowski(self) -> None:
        vec_a = [0.0, 0.0]
        vec_b = [3.0, 4.0]
        manhattan = manhattan_distance(vec_a, vec_b)
        mink = minkowski_distance(vec_a, vec_b, p=1.0)
        assert manhattan == pytest.approx(mink)

    def test_chebyshev_from_minkowski_approx(self) -> None:
        vec_a = [0.0, 0.0]
        vec_b = [3.0, 4.0]
        cheby = chebyshev_distance(vec_a, vec_b)
        mink = minkowski_distance(vec_a, vec_b, p=100.0)
        assert cheby == pytest.approx(mink)

    def test_vector_add_then_subtract_returns_original(self) -> None:
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [4.0, 5.0, 6.0]
        added = vector_add(vec_a, vec_b)
        result = vector_subtract(added, vec_b)
        assert result == pytest.approx(vec_a)

    def test_magnitude_then_normalize(self) -> None:
        vec = [3.0, 4.0]
        mag = magnitude(vec)
        normalized = normalize_vector(vec)
        assert normalized == pytest.approx([3.0 / mag, 4.0 / mag])
