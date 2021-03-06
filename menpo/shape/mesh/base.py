# coding=utf-8
from collections import Counter
import numpy as np
from warnings import warn

Delaunay = None  # expensive, from scipy.spatial

from .. import PointCloud
from ..adjacency import mask_adjacency_array, reindex_adjacency_array

from .normals import compute_normals


def trilist_to_adjacency_array(trilist):
    wrap_around_adj = np.hstack([trilist[:, -1][..., None],
                                 trilist[:, 0][..., None]])
    # Build the array of all pairs
    return np.concatenate([trilist[:, :2],
                           trilist[:, 1:],
                           wrap_around_adj])


class TriMesh(PointCloud):
    r"""
    A :map:`PointCloud` with a connectivity defined by a triangle list. These
    are designed to be explicitly 2D or 3D.

    Parameters
    ----------
    points : ``(n_points, n_dims)`` `ndarray`
        The array representing the points.
    trilist : ``(M, 3)`` `ndarray` or ``None``, optional
        The triangle list. If `None`, a Delaunay triangulation of
        the points will be used instead.
    copy: `bool`, optional
        If ``False``, the points will not be copied on assignment.
        Any trilist will also not be copied.
        In general this should only be used if you know what you are doing.
    """
    def __init__(self, points, trilist=None, copy=True):
        super(TriMesh, self).__init__(points, copy=copy)
        if trilist is None:
            global Delaunay
            if Delaunay is None:
                from scipy.spatial import Delaunay  # expensive
            trilist = Delaunay(points).simplices
        if not copy:
            if not trilist.flags.c_contiguous:
                warn('The copy flag was NOT honoured. A copy HAS been made. '
                     'Please ensure the data you pass is C-contiguous.')
                trilist = np.array(trilist, copy=True, order='C')
        else:
            trilist = np.array(trilist, copy=True, order='C')
        self.trilist = trilist

    def __str__(self):
        return '{}, n_tris: {}'.format(PointCloud.__str__(self),
                                       self.n_tris)

    @property
    def n_tris(self):
        r"""
        The number of triangles in the triangle list.

        :type: `int`
        """
        return len(self.trilist)

    def tojson(self):
        r"""
        Convert this :map:`TriMesh` to a dictionary representation suitable
        for inclusion in the LJSON landmark format. Note that this enforces a
        simpler representation, and as such is not suitable for
        a permanent serialization of a :map:`TriMesh` (to be clear,
        :map:`TriMesh`'s serialized as part of a landmark set will be rebuilt
        as a :map:`PointUndirectedGraph`).

        Returns
        -------
        json : `dict`
            Dictionary with ``points`` and ``connectivity`` keys.
        """
        return self.as_pointgraph().tojson()

    def from_mask(self, mask):
        """
        A 1D boolean array with the same number of elements as the number of
        points in the TriMesh. This is then broadcast across the dimensions
        of the mesh and returns a new mesh containing only those
        points that were ``True`` in the mask.

        Parameters
        ----------
        mask : ``(n_points,)`` `ndarray`
            1D array of booleans

        Returns
        -------
        mesh : :map:`TriMesh`
            A new mesh that has been masked.
        """
        if mask.shape[0] != self.n_points:
            raise ValueError('Mask must be a 1D boolean array of the same '
                             'number of entries as points in this TriMesh.')

        tm = self.copy()
        if np.all(mask):  # Fast path for all true
            return tm
        else:
            # Recalculate the mask to remove isolated vertices
            isolated_mask = self._isolated_mask(mask)
            # Recreate the adjacency array with the updated mask
            masked_adj = mask_adjacency_array(isolated_mask, self.trilist)
            tm.trilist = reindex_adjacency_array(masked_adj)
            tm.points = tm.points[isolated_mask, :]
            return tm

    def _isolated_mask(self, mask):
        # Find the triangles we need to keep
        masked_adj = mask_adjacency_array(mask, self.trilist)
        # Find isolated vertices (vertices that don't exist in valid
        # triangles)
        isolated_indices = np.setdiff1d(np.nonzero(mask)[0], masked_adj)

        # Create a 'new mask' that contains the points the use asked
        # for MINUS the points that we can't create triangles for
        new_mask = mask.copy()
        new_mask[isolated_indices] = False
        return new_mask

    def as_pointgraph(self, copy=True, skip_checks=False):
        """
        Converts the TriMesh to a :map:`PointUndirectedGraph`.

        Parameters
        ----------
        copy : `bool`, optional
            If ``True``, the graph will be a copy.
        skip_checks : `bool`, optional
            If ``True``, no checks will be performed.

        Returns
        -------
        pointgraph : :map:`PointUndirectedGraph`
            The point graph.
        """
        from .. import PointUndirectedGraph
        from ..graph import _convert_edges_to_symmetric_adjacency_matrix
        # Since we have triangles we need the last connection
        # that 'completes' the triangle
        adjacency_matrix = _convert_edges_to_symmetric_adjacency_matrix(
            trilist_to_adjacency_array(self.trilist), self.points.shape[0])
        pg = PointUndirectedGraph(self.points, adjacency_matrix, copy=copy,
                                  skip_checks=skip_checks)
        # This is always a copy
        pg.landmarks = self.landmarks
        return pg

    def vertex_normals(self):
        r"""
        Compute the per-vertex normals from the current set of points and
        triangle list. Only valid for 3D dimensional meshes.

        Returns
        -------
        normals : ``(n_points, 3)`` `ndarray`
            Normal at each point.

        Raises
        ------
        ValueError
            If mesh is not 3D
        """
        if self.n_dims != 3:
            raise ValueError("Normals are only valid for 3D meshes")
        return compute_normals(self.points, self.trilist)[0]

    def tri_normals(self):
        r"""
        Compute the triangle face normals from the current set of points and
        triangle list. Only valid for 3D dimensional meshes.

        Returns
        -------
        normals : ``(n_tris, 3)`` `ndarray`
            Normal at each triangle face.

        Raises
        ------
        ValueError
            If mesh is not 3D
        """
        if self.n_dims != 3:
            raise ValueError("Normals are only valid for 3D meshes")
        return compute_normals(self.points, self.trilist)[1]

    def tri_areas(self):
        r"""The area of each triangle face.

        Returns
        -------
        areas : ``(n_tris,)`` `ndarray`
            Area of each triangle, ordered as the trilist is

        Raises
        ------
        ValueError
            If mesh is not 2D or 3D
        """
        t = self.points[self.trilist]
        ij, ik = t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
        if self.n_dims == 2:
            return np.cross(ij, ik) * 0.5
        elif self.n_dims == 3:
            return np.linalg.norm(np.cross(ij, ik), axis=1) * 0.5
        else:
            raise ValueError('tri_areas can only be calculated on a 2D or '
                             '3D mesh')

    def mean_tri_area(self):
        r"""The mean area of each triangle face in this :map:`TriMesh`.

        Returns
        -------
        mean_tri_area : ``float``
            The mean area of each triangle face in this :map:`TriMesh`

        Raises
        ------
        ValueError
            If mesh is not 3D
        """
        return np.mean(self.tri_areas())

    def boundary_tri_index(self):
        r"""Boolean index into triangles that are at the edge of the TriMesh

        Returns
        -------
        boundary_tri_index : ``(n_tris,)`` `ndarray`
            For each triangle (ABC), returns whether any of it's edges is not
            also an edge of another triangle (and so this triangle exists on
            the boundary of the TriMesh)
        """
        trilist = self.trilist
        # Get a sorted list of edge pairs
        edge_pairs = np.sort(np.vstack((trilist[:, [0, 1]],
                                        trilist[:, [0, 2]],
                                        trilist[:, [1, 2]])))

        # convert to a tuple per edge pair
        edges = [tuple(x) for x in edge_pairs]
        # count the occurrences of the ordered edge pairs - edge pairs that
        # occur once are at the edge of the whole mesh
        mesh_edges = (e for e, i in Counter(edges).items() if i == 1)
        # index back into the edges to find which triangles contain these edges
        return np.array(list(set(edges.index(e) % trilist.shape[0]
                                 for e in mesh_edges)))

    def edge_vectors(self):
        r"""A vector of edges of each triangle face.

        Note that there will be two edges present in cases where two triangles
        'share' an edge. Consider :meth:`unique_edge_vectors` for a
        single vector for each physical edge on the :map:`TriMesh`.

        Returns
        -------
        edges : ``(n_tris * 3, n_dims)`` `ndarray`
            For each triangle (ABC), returns the edge vectors AB, BC, CA. All
            edges are concatenated for a total of ``n_tris * 3`` edges. The
            ordering is done so that all AB vectors are first in the returned
            list, followed by BC, then CA.
        """
        t = self.points[self.trilist]
        return np.vstack((t[:, 1] - t[:, 0],
                          t[:, 2] - t[:, 1],
                          t[:, 2] - t[:, 0]))

    def edge_indices(self):
        r"""An unordered index into points that rebuilds the edges of this
        :map:`TriMesh`.

        Note that there will be two edges present in cases where two triangles
        'share' an edge. Consider :meth:`unique_edge_indices` for a single index
        for each physical edge on the :map:`TriMesh`.

        Returns
        -------
        edge_indices : ``(n_tris * 3, 2)`` `ndarray`
            For each triangle (ABC), returns the pair of point indices that
            rebuild AB, AC, BC. All edge indices are concatenated for a total
            of ``n_tris * 3`` edge_indices. The ordering is done so that all
            AB vectors are first in the returned list, followed by BC, then CA.
        """
        tl = self.trilist
        return np.vstack((tl[:, [0, 1]],
                          tl[:, [1, 2]],
                          tl[:, [2, 0]]))

    def unique_edge_indicies(self):
        r"""An unordered index into points that rebuilds the unique edges of
        this :map:`TriMesh`.

        Note that each physical edge will only be counted once in this method
        (i.e. edges shared between neighbouring triangles are only counted once
        not twice). The ordering should be considered random.

        Returns
        -------
        unique_edge_indicies : ``(n_unique_edges, 2)`` `ndarray`
            Return a point index that rebuilds all edges present in this
            :map:`TriMesh` only once.
        """
        # Get a sorted list of edge pairs. sort ensures that each edge is
        # ordered from lowest index to highest.
        edge_pairs = np.sort(self.edge_indices())

        # We want to remove duplicates - this is a little hairy: basically we
        # get a view on the array where each pair is considered by numpy to be
        # one item
        edge_pair_view = np.ascontiguousarray(edge_pairs).view(
            np.dtype((np.void, edge_pairs.dtype.itemsize * edge_pairs.shape[1])))
        # Now we can use this view to ask for only unique edges...
        unique_edge_index = np.unique(edge_pair_view, return_index=True)[1]
        # And use that to filter our original list down
        return edge_pairs[unique_edge_index]

    def unique_edge_vectors(self):
        r"""An unordered vector of unique edges for the whole :map:`TriMesh`.

        Note that each physical edge will only be counted once in this method
        (i.e. edges shared between neighbouring triangles are only counted once
        not twice). The ordering should be considered random.

        Returns
        -------
        unique_edge_vectors : ``(n_unique_edges, n_dims)`` `ndarray`
            Vectors for each unique edge in this :map:`TriMesh`.
        """
        x = self.points[self.unique_edge_indicies()]
        return x[:, 1] - x[:, 0]

    def edge_lengths(self):
        r"""The length of each edge in this :map:`TriMesh`.

        Note that there will be two edges present in cases where two triangles
        'share' an edge. Consider :meth:`unique_edge_indices` for a single
        index for each physical edge on the :map:`TriMesh`. The ordering
        matches the case for edges and edge_indices.

        Returns
        -------
        edge_lengths : ``(n_tris * 3, )`` `ndarray`
            Scalar euclidean lengths for each edge in this :map:`TriMesh`.
        """
        return np.linalg.norm(self.edge_vectors(), axis=1)

    def unique_edge_lengths(self):
        r"""The length of each edge in this :map:`TriMesh`.

        Note that each physical edge will only be counted once in this method
        (i.e. edges shared between neighbouring triangles are only counted once
        not twice). The ordering should be considered random.

        Returns
        -------
        edge_lengths : ``(n_tris * 3, )`` `ndarray`
            Scalar euclidean lengths for each edge in this :map:`TriMesh`.
        """
        return np.linalg.norm(self.unique_edge_vectors(), axis=1)

    def mean_edge_length(self, unique=True):
        r"""The mean length of each edge in this :map:`TriMesh`.

        Parameters
        ----------
        unique : `bool`, optional
            If ``True``, each shared edge will only be counted once towards
            the average. If false, shared edges will be counted twice.

        Returns
        -------
        mean_edge_length : ``float``
            The mean length of each edge in this :map:`TriMesh`
        """
        return np.mean(self.unique_edge_lengths() if unique
                       else self.edge_lengths())

    def _view_2d(self, figure_id=None, new_figure=False, image_view=True,
                 render_lines=True, line_colour='r', line_style='-',
                 line_width=1., render_markers=True, marker_style='o',
                 marker_size=20, marker_face_colour='k', marker_edge_colour='k',
                 marker_edge_width=1., render_axes=True,
                 axes_font_name='sans-serif', axes_font_size=10,
                 axes_font_style='normal', axes_font_weight='normal',
                 axes_x_limits=None, axes_y_limits=None, figure_size=(10, 8),
                 label=None):
        r"""
        Visualization of the TriMesh in 2D.

        Returns
        -------
        figure_id : `object`, optional
            The id of the figure to be used.
        new_figure : `bool`, optional
            If ``True``, a new figure is created.
        image_view : `bool`, optional
            If ``True`` the TriMesh will be viewed as if it is in the image
            coordinate system.
        render_lines : `bool`, optional
            If ``True``, the edges will be rendered.
        line_colour : See Below, optional
            The colour of the lines.
            Example options::

                {r, g, b, c, m, k, w}
                or
                (3, ) ndarray

        line_style : ``{-, --, -., :}``, optional
            The style of the lines.
        line_width : `float`, optional
            The width of the lines.
        render_markers : `bool`, optional
            If ``True``, the markers will be rendered.
        marker_style : See Below, optional
            The style of the markers. Example options ::

                {., ,, o, v, ^, <, >, +, x, D, d, s, p, *, h, H, 1, 2, 3, 4, 8}

        marker_size : `int`, optional
            The size of the markers in points^2.
        marker_face_colour : See Below, optional
            The face (filling) colour of the markers.
            Example options ::

                {r, g, b, c, m, k, w}
                or
                (3, ) ndarray

        marker_edge_colour : See Below, optional
            The edge colour of the markers.
            Example options ::

                {r, g, b, c, m, k, w}
                or
                (3, ) ndarray

        marker_edge_width : `float`, optional
            The width of the markers' edge.
        render_axes : `bool`, optional
            If ``True``, the axes will be rendered.
        axes_font_name : See Below, optional
            The font of the axes.
            Example options ::

                {serif, sans-serif, cursive, fantasy, monospace}

        axes_font_size : `int`, optional
            The font size of the axes.
        axes_font_style : {``normal``, ``italic``, ``oblique``}, optional
            The font style of the axes.
        axes_font_weight : See Below, optional
            The font weight of the axes.
            Example options ::

                {ultralight, light, normal, regular, book, medium, roman,
                semibold, demibold, demi, bold, heavy, extra bold, black}

        axes_x_limits : (`float`, `float`) `tuple` or ``None``, optional
            The limits of the x axis.
        axes_y_limits : (`float`, `float`) `tuple` or ``None``, optional
            The limits of the y axis.
        figure_size : (`float`, `float`) `tuple` or ``None``, optional
            The size of the figure in inches.
        label : `str`, optional
            The name entry in case of a legend.

        Returns
        -------
        viewer : :map:`PointGraphViewer2d`
            The viewer object.
        """
        from menpo.visualize import PointGraphViewer2d

        return PointGraphViewer2d(
            figure_id, new_figure, self.points,
            trilist_to_adjacency_array(self.trilist)).render(
                image_view=image_view, render_lines=render_lines,
                line_colour=line_colour, line_style=line_style,
                line_width=line_width, render_markers=render_markers,
                marker_style=marker_style, marker_size=marker_size,
                marker_face_colour=marker_face_colour,
                marker_edge_colour=marker_edge_colour,
                marker_edge_width=marker_edge_width, render_axes=render_axes,
                axes_font_name=axes_font_name, axes_font_size=axes_font_size,
                axes_font_style=axes_font_style,
                axes_font_weight=axes_font_weight, axes_x_limits=axes_x_limits,
                axes_y_limits=axes_y_limits, figure_size=figure_size,
                label=label)

    def _view_3d(self, figure_id=None, new_figure=False, **kwargs):
        r"""
        Visualization of the TriMesh in 3D.

        Parameters
        ----------
        figure_id : `object`, optional
            The id of the figure to be used.
        new_figure : `bool`, optional
            If ``True``, a new figure is created.

        Returns
        -------
        viewer : TriMeshViewer3D
            The Menpo3D viewer object.
        """
        try:
            from menpo3d.visualize import TriMeshViewer3d
            return TriMeshViewer3d(figure_id, new_figure,
                                   self.points, self.trilist).render(**kwargs)
        except ImportError:
            from menpo.visualize import Menpo3dErrorMessage
            raise ImportError(Menpo3dErrorMessage)

    def view_widget(self, browser_style='buttons', figure_size=(10, 8),
                    style='coloured'):
        r"""
        Visualization of the TriMesh using the :map:`visualize_pointclouds`
        widget.

        Parameters
        ----------
        browser_style : {``'buttons'``, ``'slider'``}, optional
            It defines whether the selector of the objects will have the form of
            plus/minus buttons or a slider.
        figure_size : (`int`, `int`) `tuple`, optional
            The initial size of the rendered figure.
        style : {``'coloured'``, ``'minimal'``}, optional
            If ``'coloured'``, then the style of the widget will be coloured. If
            ``minimal``, then the style is simple using black and white colours.
        """
        from menpo.visualize import visualize_pointclouds
        visualize_pointclouds(self, figure_size=figure_size, style=style,
                              browser_style=browser_style)
