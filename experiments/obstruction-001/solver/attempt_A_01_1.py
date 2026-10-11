def fib(n):
    """Return the nth Fibonacci number (fib(0)=0, fib(1)=1)."""
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)
