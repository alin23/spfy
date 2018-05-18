import numpy as _np
from cached_property import cached_property


class frange:
    """
    Return an object can be used to generate a generator or an array
    of floats from start (inclusive) to stop (exclusive) by step.
    This object stores the start, stop, step and length of
    the data. Uses less memory than storing a large array.
    Example
    -------
    An example of how to use this class to generate some data is
    as follows for some time data between 0 and 2 in steps of
    1e-3 (0.001)::
        you can create an frange object like so
        $ time = frange(0, 2, 1e-3)
        you can print the length of the array it will generate
        $ printlen(time) # prints length of frange, just like an array or list
        you can create a generator
        $ generator = time.generator # gets a generator instance
        $ for i in generator: # iterates through printing each element
        $     print(i)
        you can create a numpy array
        $ array = time.array # gets an array instance
        $ newarray = 5 * array # multiplies array by 5
        you can also get the start, stop and step by accessing the slice parameters
        $ start = time.start
        $ stop = time.stop
        $ step = time.step
    """

    def __init__(self, start, stop, step):
        """
        Intialises frange class instance. Sets start, top, step and
        len properties.
        Parameters
        ----------
        start : float
            starting point
        stop : float
            stopping point
        step : float
           stepping interval
        """
        self.slice = slice(start, stop, step)

    @property
    def start(self):
        return self.slice.start

    @property
    def step(self):
        return self.slice.step

    @property
    def stop(self):
        return self.slice.stop

    @cached_property
    def array(self):
        return self.get_array()

    @cached_property
    def generator(self):
        return self.get_generator()

    def __getitem__(self, idx):
        if idx == -1:
            return self.stop - self.step

        if idx == 0:
            return self.start

        return self.array[idx]

    def get_generator(self):
        """
        Returns a generator for the frange object instance.
        Returns
        -------
        gen : generator
            A generator that yields successive samples from start (inclusive)
            to stop (exclusive) in step steps.
        """
        return drange(self.start, self.stop, self.step)

    def get_array(self):
        """
        Returns an numpy array containing the values from start (inclusive)
        to stop (exclusive) in step steps.
        Returns
        -------
        array : ndarray
            Array of values from start (inclusive)
            to stop (exclusive) in step steps.
        """
        return _np.arange(self.start, self.stop, self.step)

    def __len__(self):
        return self.array.size

    def __iter__(self):
        return self.generator


def drange(start, stop, step):
    """
    A generator that yields successive samples from start (inclusive)
    to stop (exclusive) in step intervals.
    Parameters
    ----------
    start : float
        starting point
    stop : float
        stopping point
    step : float
        stepping interval
    Yields
    ------
    x : float
        next sample
    """
    x = start
    if step > 0:
        while x + step <= stop:  # produces same behaviour as numpy.arange
            yield x

            x += step
    elif step < 0:
        while x + step >= stop:  # produces same behaviour as numpy.arange
            yield x

            x += step
    else:
        raise ZeroDivisionError("Step must be non-zero")
