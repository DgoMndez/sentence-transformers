from sentence_transformers.evaluation import SentenceEvaluator, SimilarityFunction
import logging
import os
import csv
from sklearn.metrics.pairwise import paired_cosine_distances, paired_euclidean_distances, paired_manhattan_distances
import numpy as np
from typing import List, Literal, Optional
from sentence_transformers import InputExample


logger = logging.getLogger(__name__)

class MSESimilarityEvaluator(SentenceEvaluator):
    """
    Evaluate a model based on the similarity of the embeddings by calculating the MSE
    in comparison to the gold standard labels.
    The metrics are the cosine similarity as well as euclidean and Manhattan distance.
    The returned score is the MSE with a specified metric.

    The results are written in a CSV. If a CSV already exists, then values are appended.

    This metric is better when lower, so don't forget to set greater_is_better = False
    in TrainingArguments if you need it.
    """

    def __init__(
        self,
        sentences1: List[str],
        sentences2: List[str],
        scores: List[float],
        batch_size: int = 16,
        main_similarity: SimilarityFunction = None,
        name: str = "",
        show_progress_bar: bool = False,
        write_csv: bool = True,
        precision: Optional[Literal["float32", "int8", "uint8", "binary", "ubinary"]] = None,
    ):
        """
        Constructs an evaluator based for the dataset

        The labels need to indicate the similarity between the sentences.

        :param sentences1:  List with the first sentence in a pair
        :param sentences2: List with the second sentence in a pair
        :param scores: Similarity score between sentences1[i] and sentences2[i]
        :param write_csv: Write results to a CSV file
        :param precision: The precision to use for the embeddings. Can be "float32", "int8", "uint8", "binary", or
            "ubinary". Defaults to None.
        """
        self.sentences1 = sentences1
        self.sentences2 = sentences2
        self.scores = scores
        self.write_csv = write_csv
        self.precision = precision

        assert len(self.sentences1) == len(self.sentences2)
        assert len(self.sentences1) == len(self.scores)
        
        self.main_similarity = main_similarity
        self.name = name

        self.batch_size = batch_size
        if show_progress_bar is None:
            show_progress_bar = (
                logger.getEffectiveLevel() == logging.INFO or logger.getEffectiveLevel() == logging.DEBUG
            )
        self.show_progress_bar = show_progress_bar

        self.csv_file = (
            "MSE_similarity_evaluation"
            + ("_" + name if name else "")
            + ("_" + precision if precision else "")
            + "_results.csv"
        )
        self.csv_headers = [
            "epoch",
            "steps",
            "MSE_cosine",
            "MSE_euclidean",
            "MSE_manhattan",
            "MSE_dot",
        ]

    @classmethod
    def from_input_examples(cls, examples: List[InputExample], **kwargs):
        sentences1 = []
        sentences2 = []
        scores = []

        for example in examples:
            sentences1.append(example.texts[0])
            sentences2.append(example.texts[1])
            scores.append(example.label)
        return cls(sentences1, sentences2, scores, **kwargs)

    def __call__(self, model, output_path: str = None, epoch: int = -1, steps: int = -1) -> float:
        if epoch != -1:
            if steps == -1:
                out_txt = " after epoch {}:".format(epoch)
            else:
                out_txt = " in epoch {} after {} steps:".format(epoch, steps)
        else:
            out_txt = ":"

        logger.info("EmbeddingSimilarityEvaluator: Evaluating the model on " + self.name + " dataset" + out_txt)
        if self.precision is not None:
            embeddings1 = model.encode(
                self.sentences1,
                batch_size=self.batch_size,
                show_progress_bar=self.show_progress_bar,
                convert_to_numpy=True,
                precision=self.precision,
                normalize_embeddings=bool(self.precision),
            )
            embeddings2 = model.encode(
                self.sentences2,
                batch_size=self.batch_size,
                show_progress_bar=self.show_progress_bar,
                convert_to_numpy=True,
                precision=self.precision,
                normalize_embeddings=bool(self.precision),
            )
            # Binary and ubinary embeddings are packed, so we need to unpack them for the distance metrics
            if self.precision == "binary":
                embeddings1 = (embeddings1 + 128).astype(np.uint8)
                embeddings2 = (embeddings2 + 128).astype(np.uint8)
            if self.precision in ("ubinary", "binary"):
                embeddings1 = np.unpackbits(embeddings1, axis=1)
                embeddings2 = np.unpackbits(embeddings2, axis=1)
        else:
            embeddings1 = model.encode(
                self.sentences1,
                batch_size=self.batch_size,
                show_progress_bar=self.show_progress_bar,
                convert_to_numpy=True,
            )
            embeddings2 = model.encode(
                self.sentences2,
                batch_size=self.batch_size,
                show_progress_bar=self.show_progress_bar,
                convert_to_numpy=True,
            )

        labels = self.scores

        cosine_scores = 1 - (paired_cosine_distances(embeddings1, embeddings2))
        manhattan_distances = -paired_manhattan_distances(embeddings1, embeddings2)
        euclidean_distances = -paired_euclidean_distances(embeddings1, embeddings2)
        dot_products = np.array([np.dot(emb1, emb2) for emb1, emb2 in zip(embeddings1, embeddings2)])

        eval_mse_cosine = np.mean((cosine_scores - labels) ** 2)
        eval_mse_manhattan = np.mean((manhattan_distances - labels) ** 2)
        eval_mse_euclidean = np.mean((euclidean_distances - labels) ** 2)
        eval_mse_dot = np.mean((dot_products - labels) ** 2)

        logger.info(
            "Cosine-Similarity :\tMSE: {:.6f}".format(eval_mse_cosine)
        )
        logger.info(
            "Manhattan-Distance:\tMSE: {:.6f}".format(eval_mse_manhattan)
        )
        logger.info(
            "Euclidean-Distance:\tMSE: {:.6f}".format(eval_mse_euclidean)
        )
        logger.info(
            "Dot-Product-Similarity:\tMSE: {:.6f}".format(eval_mse_dot)
        )

        if output_path is not None and self.write_csv:
            csv_path = os.path.join(output_path, self.csv_file)
            output_file_exists = os.path.isfile(csv_path)
            with open(csv_path, newline="", mode="a" if output_file_exists else "w", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not output_file_exists:
                    writer.writerow(self.csv_headers)

                writer.writerow(
                    [
                        epoch,
                        steps,
                        eval_mse_cosine,
                        eval_mse_euclidean,
                        eval_mse_manhattan,
                        eval_mse_dot,
                    ]
                )

        if self.main_similarity == SimilarityFunction.COSINE:
            return eval_mse_cosine
        elif self.main_similarity == SimilarityFunction.EUCLIDEAN:
            return eval_mse_euclidean
        elif self.main_similarity == SimilarityFunction.MANHATTAN:
            return eval_mse_manhattan
        elif self.main_similarity == SimilarityFunction.DOT_PRODUCT:
            return eval_mse_dot
        elif self.main_similarity is None:
            return min(eval_mse_cosine, eval_mse_manhattan, eval_mse_euclidean, eval_mse_dot)
            # This metric is better when lower
            # so don't forget to set greater_is_better = False in TrainingArguments
        else:
            raise ValueError("Unknown main_similarity value")