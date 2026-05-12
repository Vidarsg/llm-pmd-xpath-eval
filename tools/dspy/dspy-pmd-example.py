import dspy
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity

##############################################################################
# This function is just a metric for evaluating how good the predictions are. You can use your other metrics if you want.


def prediction_similarity(ex: dspy.Example, pred: dspy.Prediction) -> float:
    vectorizer = CountVectorizer()
    vectors = vectorizer.fit_transform([ex.xpath, pred.xpath])
    return float(cosine_similarity(vectors[0:1], vectors[1:2])[0][0])
#############################################################################
# This function saves a rule/prediction pair to a file.


def save_prediction(rule: str, pred: dspy.Prediction, filename: str):
    with open(filename, "w") as f:
        f.write('######## RULE: ########\n')
        f.write(rule)
        f.write('\n\n######## PREDICTED XPATH: ########\n')
        f.write(pred.xpath)
#############################################################################


# List of models to try. It seems you actually need to prepend "openai/" to the model name when using the NTNU API, even for non-OpenAI models.
IDUN_MODELS = [
    'google/gemma-4-31B-it',
    'openai/gpt-oss-120b',
    'Qwen/Qwen3.5-122B-A10B-FP8'
]
API_KEY = 'env key goes here'


def run_with_model(model_id=0):
    idun = dspy.LM(IDUN_MODELS[model_id], api_key=API_KEY,
                   api_base="https://llm.hpc.ntnu.no/")
    dspy.configure(lm=idun)

    log_id = f"model-{model_id}"

    # Here I just copy-pasted two rules and their corresponding Xpath expressions from the PMD website. Not very nice, but it works.

    ################ AvoidAccessibilityAlteration ################
    rule1 = """AvoidAccessibilityAlteration

    Methods such as getDeclaredConstructors(), getDeclaredMethods(), and getDeclaredFields() also return private constructors, methods and fields. These can be made accessible by calling setAccessible(true). This gives access to normally protected data which violates the principle of encapsulation.

    This rule detects calls to setAccessible and finds possible accessibility alterations. If the call to setAccessible is wrapped within a PrivilegedAction, then the access alteration is assumed to be deliberate and is not reported.

    Note that with Java 17 the Security Manager, which is used for PrivilegedAction execution, is deprecated: JEP 411: Deprecate the Security Manager for Removal. For future-proof code, deliberate access alteration should be suppressed using the usual suppression methods (e.g. by using @SuppressWarnings annotation).
    """
    xpath1 = """//MethodCall[
            pmd-java:matchesSig("java.lang.reflect.AccessibleObject#setAccessible(boolean)")
        or pmd-java:matchesSig("_#setAccessible(java.lang.reflect.AccessibleObject[],boolean)")
        ]
        [not(ArgumentList/BooleanLiteral[@True = false()])]
        (: exclude anonymous privileged action classes :)
        [not(ancestor::ConstructorCall[1][pmd-java:typeIs('java.security.PrivilegedAction')]/AnonymousClassDeclaration)]
        (: exclude inner privileged action classes :)
        [not(ancestor::ClassDeclaration[1][pmd-java:typeIs('java.security.PrivilegedAction')])]
        (: exclude privileged action lambdas :)
        [not(ancestor::LambdaExpression[pmd-java:typeIs('java.security.PrivilegedAction')])]
    """
    #############################################################################

    ################ AvoidDecimalLiteralsInBigDecimalConstructor ################

    rule2 = """AvoidDecimalLiteralsInBigDecimalConstructor ️

    One might assume that the result of "new BigDecimal(0.1)" is exactly equal to 0.1, but it is actually equal to .1000000000000000055511151231257827021181583404541015625. This is because 0.1 cannot be represented exactly as a double (or as a binary fraction of any finite length). Thus, the long value that is being passed in to the constructor is not exactly equal to 0.1, appearances notwithstanding.

    The (String) constructor, on the other hand, is perfectly predictable: ‘new BigDecimal("0.1")’ is exactly equal to 0.1, as one would expect. Therefore, it is generally recommended that the (String) constructor be used in preference to this one.
    """

    xpath2 = """//ConstructorCall[pmd-java:matchesSig('java.math.BigDecimal#new(double)')]"""
    #############################################################################

    # Data to be used for prompt optimization
    data = [[rule1, xpath1], [rule2, xpath2]]
    # It needs to be formatted in a specific way for the framework. It needs to be wrapped in a dspy.Example object.
    trainset = [dspy.Example(rule=r, xpath=x).with_inputs('rule')
                for r, x in data]

    # Define the initial Chain of Thought. The signature defines the input and output of the CoT, and the instructions are what the optimizer will use to optimize the CoT.
    cot = dspy.ChainOfThought(
        dspy.Signature(
            # Signature that defines inputs and outouts of the model.
            "rule : str -> xpath : str",
            # This is the prompt, you can add your initial prompt here.
            instructions="You are a helpful assistant for Java developers. You get a description of a coding rule, and you need to write an XPath expression that finds code that violates this rule."
        )
    )
    # Saves the initial prompt and other metadata - just to be able to see it
    cot.save("cot-initial.json")
    with open(f"{log_id}-prompt-initial.md", "w") as f:
        f.write(cot.predict.signature.instructions)

    # We can also see how the prompt performs on data outside the training set. Here I test with the "another_rule" rule.
    another_rule = """ClassCastExceptionWithToArray ️

    When deriving an array of a specific class from your Collection, one should provide an array of the same class as the parameter of the toArray() method. Doing otherwise will result in a ClassCastException."""

    predicted_output_initial = cot.predict(rule=another_rule)
    save_prediction(another_rule, predicted_output_initial,
                    f"{log_id}-predicted-initial.md")

    # Uses the MIPROv2 optimizer from the framework.
    # Here you need to provide a metric to evaluate the predictions. I used a simple definition of cosine similarity.
    # The "auto" parameter defines how hard it will try to optimized. "light" is a good default, other options are "medium" and "heavy".
    tp = dspy.MIPROv2(metric=prediction_similarity,
                      auto="light", num_threads=24)
    optimized_cot = tp.compile(cot, trainset=trainset)

    # We now have an optimized prompt. We can save it with its metadata.
    optimized_cot.save("cot-optimized.json")
    optimized_prompt = optimized_cot.predict.signature.instructions
    with open(f"{log_id}-prompt-optimized.md", "w") as f:
        f.write(optimized_prompt)

    predicted_output_optimized = optimized_cot.predict(rule=another_rule)
    save_prediction(another_rule, predicted_output_optimized,
                    f"{log_id}-predicted-optimized.md")


run_with_model(0)
run_with_model(1)
run_with_model(2)
