import random

class Human:
    def __init__(self, name: str, age: int):
        self.name = name
        self.age = age

    @staticmethod
    def say_hello():
        print("Hello!")

    def say_hello_with_name(self):
        print("%s: Hello!" % self.name)

    def say_random_number(self, a: int, b: int):
        print("{0}: My random number is {1}".format(self.name, random.randint(a, b)))

    def say_input(self):
        print("{0}: {1}".format(self.name, input("What should I say?: ")))

    def count_to_age_times_n(self, n: int):
        for i in range(self.age*n):
            print(i)

    def get_square_root_of_age(self) -> float:
        return self.age ** 0.5
