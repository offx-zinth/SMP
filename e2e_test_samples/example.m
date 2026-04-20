% Example MATLAB module for parser testing

classdef Calculator
    % Calculator class for basic operations
    
    methods
        function result = add(obj, a, b)
            % Add two numbers
            result = a + b;
        end
        
        function result = subtract(obj, a, b)
            % Subtract two numbers
            result = a - b;
        end
    end
end

function result = multiply(x, y)
    % Multiply two floats
    result = x * y;
end

function result = divide(x, y)
    % Divide two floats
    if y == 0
        error('Cannot divide by zero');
    end
    result = x / y;
end
