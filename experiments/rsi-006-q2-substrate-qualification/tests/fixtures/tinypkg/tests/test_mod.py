from tinypkg.mod import sign, double


def test_sign_pos():
    assert sign(5) == 1


def test_sign_neg():
    assert sign(-5) == -1


def test_sign_zero():
    assert sign(0) == 0


def test_double():
    assert double(21) == 42
