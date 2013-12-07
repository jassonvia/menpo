import numpy as np
from scipy.linalg.blas import dgemm
from pybug.decomposition import principal_component_decomposition
from pybug.model.base import MeanInstanceLinearModel


class PCAModel(MeanInstanceLinearModel):
    """
    A :class:`MeanLinearInstanceModel` where the components are Principal
    Components.

    Principal Component Analysis (PCA) by Eigenvalue Decomposition of the
    data's scatter matrix.

    For details of the implementation of PCA, see :func:`pybug.decomposition
    .principal_component_decomposition`.

    Parameters
    ----------
    samples: list of :class:`pybug.base.Vectorizable`
        List of samples to build the model from.

    center : bool, optional
        When True (True by default) PCA is performed after mean centering the
        data. If False the data is assumed to be centred, and the mean will
        be 0.

    bias: bool, optional
        When True (False by default) a biased estimator of the covariance
        matrix is used, i.e.:

            \frac{1}{N} \sum_i^N \mathbf{x}_i \mathbf{x}_i^T

        instead of default:

            \frac{1}{N-1} \sum_i^N \mathbf{x}_i \mathbf{x}_i^T
    """
    def __init__(self, samples, center=True, bias=False):
        self.samples = samples
        self.center = center
        self.bias = bias
        # build data matrix
        n_samples = len(samples)
        n_features = samples[0].n_parameters
        data = np.zeros((n_samples, n_features))
        for i, sample in enumerate(samples):
            data[i] = sample.as_vector()

        eigenvectors, eigenvalues, mean_vector = \
            principal_component_decomposition(data, whiten=False,
                                              center=center, bias=bias)
        self._eigenvalues = eigenvalues
        super(PCAModel, self).__init__(eigenvectors, mean_vector, samples[0])

    @property
    def whitened_components(self):
        return self.components / (
            np.sqrt(self.eigenvalues + self.noise_variance)[:, None])

    @property
    def n_samples(self):
        return len(self.samples)

    @property
    def eigenvalues(self):
        return self._eigenvalues[:self.n_components]

    @property
    def eigenvalues_ratio(self):
        return self.eigenvalues / self.eigenvalues.sum()

    @property
    def noise_variance(self):
        if self.n_components == self.n_available_components:
            return 0
        else:
            return self._eigenvalues[self.n_components:].mean()

    @property
    def inverse_noise_variance(self):
        noise_variance = self.noise_variance
        if noise_variance == 0:
            raise ValueError("noise variance is nil - cannot take the "
                             "inverse")
        else:
            return 1.0 / noise_variance

    def component_vector(self, index, with_mean=True, scale=1.0):
        r"""
        A particular component of the model, in vectorized form.

        Parameters
        ----------
        index : int
            The component that is to be returned

        with_mean: boolean (optional)
            If True, the component will be blended with the mean vector
            before being returned. If not, the component is returned on it's
            own.

            Default: True
        scale : float
            A scale factor that should be applied to the component. Only
            valid in the case where with_mean is True. The scale is applied
            in units of standard deviations (so a scale of 1.0
            with_mean visualizes the mean plus 1 std. dev of the component
            in question).

        :type: (n_features,) ndarray
        """
        if with_mean:
            # on PCA, scale is in units of std. deviations...
            scaled_eigval = scale * np.sqrt(self.eigenvalues[index])
            return (scaled_eigval * self.components[index]) + self.mean_vector
        else:
            return self.components[index]

    def trim_components(self, n_components=None):
        r"""
        Permanently trims the components down to a certain amount.

        Parameters
        ----------

        n_components: int, optional
            The number of components that are kept. If None,
            self.n_components is used.
        """
        # trim the super version
        super(PCAModel, self).trim_components(n_components=n_components)
        # .. and make sure that the eigenvalues are trimmed too
        self._eigenvalues = self._eigenvalues[:self.n_available_components]

    def distance_to_subspace(self, instance):
        """
        Returns a version of ``instance`` where all the basis of the model
        have been projected out and which has been scaled by the inverse of
        the ``noise_variance``

        Parameters
        ----------
        instance : :class:`pybug.base.Vectorizable`
            A novel instance.

        Returns
        -------
        scaled_projected_out : ``self.instance_class``
            A copy of ``instance``, with all basis of the model projected out
            and scaled by the inverse of the ``noise_variance``.
        """
        vec_instance = self.distance_to_subspace_vector(instance.as_vector())
        return instance.from_vector(vec_instance)

    def distance_to_subspace_vector(self, vector_instance):
        """
        Returns a version of ``instance`` where all the basis of the model
        have been projected out and which has been scaled by the inverse of
        the ``noise_variance``.

        Parameters
        ----------
        vector_instance : (n_features,) ndarray
            A novel vector.

        Returns
        -------
        scaled_projected_out: (n_features,) ndarray
            A copy of ``vector_instance`` with all basis of the model projected
            out and scaled by the inverse of the ``noise_variance``.
        """
        return (self.inverse_noise_variance *
                self.project_out_vectors(vector_instance))

    def project_whitened(self, instance):
        """
        Returns a sheared (non-orthogonal) reconstruction of ``instance``.

        Parameters
        ----------
        instance : :class:`pybug.base.Vectorizable`
            A novel instance.

        Returns
        -------
        sheared_reconstruction : ``self.instance_class``
            A sheared (non-orthogonal) reconstruction of ``instance``.
        """
        vector_instance = self.project_whitened_vector(instance.as_vector())
        return instance.from_vector(vector_instance)

    def project_whitened_vector(self, vector_instance):
        """
        Returns a sheared (non-orthogonal) reconstruction of
        ``vector_instance``.

        Parameters
        ----------
        vector_instance : (n_features,) ndarray
            A novel vector.

        Returns
        -------
        sheared_reconstruction : (n_features,) ndarray
            A sheared (non-orthogonal) reconstruction of ``vector_instance``
        """
        whitened_components = self.whitened_components
        weights = dgemm(alpha=1.0, a=vector_instance.T,
                        b=whitened_components.T, trans_a=True)
        return dgemm(alpha=1.0, a=weights.T, b=whitened_components.T,
                     trans_a=True, trans_b=True)