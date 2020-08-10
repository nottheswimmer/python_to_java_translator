# Python to Java Translator

Work in progress.

Example input/output

IN:
```python
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
```

OUT:
```java
public class Human {
    String name;
    int age;

    public Human(String name, int age) {
        
        this.name = name;
        this.age = age;
    }

    public static void say_hello() {
        
        System.out.println("Hello!");
    }

    public void say_hello_with_name() {
        
        System.out.println(String.format("%s: Hello!", this.name));
    }

    public void say_random_number(int a, int b) {
        java.util.Random random = new java.util.Random();
        System.out.println(String.format("%1$s: My random number is %2$s", this.name, a + random.nextInt(b - a)));
    }

    public void say_input() {
        java.util.Scanner scanner = new java.util.Scanner(System.in);
System.out.print("What should I say?: ");
        System.out.println(String.format("%1$s: %2$s", this.name, scanner.nextLine()));
    }

    public void count_to_age_times_n(int n) {
        
        
        for (int i = 0; i != this.age * n; i++){
            System.out.println(i);
        }
    }

    public double get_square_root_of_age() {
        
        return Math.pow(this.age, 0.5);
    }
}
```