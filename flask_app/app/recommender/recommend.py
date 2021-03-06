import copy

import pandas as pd
import numpy as np
from collections import Counter

from sklearn.neighbors import NearestNeighbors
from sklearn.decomposition import IncrementalPCA

from sklearn.feature_extraction import DictVectorizer
from sklearn.ensemble import RandomForestClassifier



def format_keywords_for_d3(keyword_counts):
    """
    Function to take a books keywords and keyword counts and 
    reuturn it in format suitable for the d3 visualization.
    """
    keywords = []
    for key, value in keyword_counts.items():
        keyword_dict = {}
        keyword_dict['name'] = key
        keyword_dict['size'] = value
        keywords.append(keyword_dict)
    return keywords


def get_book_info(book_id, book_data):
    """
    Function to return the title, author, description for a given book. 
    """
    title = book_data[book_id]['title']
    author = book_data[book_id]['author']
    description = book_data[book_id]['description']
    book_info = [title, author, description]
    return book_info





class Recommend(object):
    def __init__(self, user, Read, Book, book_data, db, ipca_model, dict_vectorizer_fit, collab_start_point, return_distances=False):
        self.user = user
        self.Read = Read
        self.Book = Book
        self.book_data = book_data
        self.db = db
        self.ipca_model = ipca_model
        self.dict_vectorizer_fit = dict_vectorizer_fit
        self.return_distances= return_distances
        self.collab_start_point = collab_start_point
        self.collab_returned = 0

    def recommend_books(self, books_selected, features_list, books_returned, up_votes, down_votes, n_collab_returned):
        """
        Function to run collaborative filtering and book-keyword similarity and return recommendations
        """
        ##" Run collaborative filtering
        collab_filter_results = self.collaborative_filtering_predict(books_selected=books_selected, up_votes=up_votes, 
                                                                    down_votes=down_votes, n_collab_returned=n_collab_returned)
        """for book in collab_filter_results:
            if book_data[book].has_key('title'):
                print ' '.join(book_data[book]['title'].split())"""
        ## Run book similarity
        recommended_books = self.apply_book_similarity_filtering(books_selected=books_selected, collab_filter_results=collab_filter_results, 
                                                                features_list=features_list, n_collab_returned=n_collab_returned, 
                                                                books_returned=books_returned, up_votes=up_votes, 
                                                                down_votes=down_votes)
        return recommended_books

    #------------------------------Collaborative Filtering--------------------------#

    def prepare_ratings_for_dv(self, books_selected, up_votes, down_votes):
        """
        Function to query the database for the ratings the user attributed to the books
        submitted. Then place ratings and book ids into format for the dict vectorizer.

        Args:
        books_selected (list of ints): A list containing the ids of the books the end-user has selected.
        self.db: Database of users, books, and ratings. 
        
        Returns:
        ratings_list (list of dicts): A list containing dictionaries where each dict is in the format book_id:rating. 
        """
        ratings_list = []
        ratings_dict= {}
        for book_id in books_selected:
            book = self.db.session.query(self.Book).filter_by(web_id=int(book_id)).first()
            book_read = self.db.session.query(self.Read).filter_by(user_id=self.user.id, book_id=book.id).first()
            rating = book_read.rating
            #ratings_dict[web_id] = rating  
            rating = 5.0
            ratings_dict[book_id] = rating
        if up_votes:
            for upvote in up_votes:
                ratings_dict[upvote] = 5
        if down_votes:
            for downvote in down_votes:
                ratings_dict[downvote] = -1   
        ratings_list.append(ratings_dict)
        return ratings_list

    def dv_transform_enduser_vector(self, ratings_list):
        """
        Use Dict Vecotrizer object fit on full users data to transform the end-user's ratings
        data into vector with similar columns. 
        
        Args:
        dict_vectorizer_fit: A dict vectorizer object fit on all user ratings
        ratings_list (list of dicts): A list containing all end-user ratings in book_id:rating 
        format.

        Returns:
        enduser_vector: A vector of the end-user's ratings fit to the structure of the full 
        rating matrix.
        
        book_names: A list of the names of the books in the order of columns in the matrices 
        """
        enduser_vector = self.dict_vectorizer_fit.transform(ratings_list)
        book_names = self.dict_vectorizer_fit.feature_names_
        return book_names, enduser_vector

    def ipca_tranform_enduser_vector(self, enduser_vector):
        """
        Use IPCA model fit on full user data transform 
        the user vector, to predict what he/she would have filled in for missing 
        values.
        """
        ipca_result = self.ipca_model.transform(enduser_vector)
        ## Transform back to vector with results
        filled_enduser_ratings = self.ipca_model.inverse_transform(ipca_result)[0]
        return filled_enduser_ratings

    def create_user_authors_list(self, books_selected):
        """
        Creates a list of the authors of the books input by the user.
        Args:
        books_selected: List of the book ids from end-user input 
        self.book_data: Full book data
        """
        user_authors_list = []
        for book_id in books_selected:
            if self.book_data.has_key(book_id) and self.book_data.has_key('author'):
                author = self.book_data[book_id]['author']
                user_authors_list.append(author)
        return user_authors_list

    def return_top_n_books(self, filled_enduser_ratings, book_names, read_authors_list, n_collab_returned, count=1):
        """
        Return the top n number of books from the ipca model results.

        Args:
        filled_ratings: The end-user vector with all book ratings predicted
        n_results: The number of results to return (most strong predictions delivered first)
        book_names: The names of the books, in order of vector columns.
        self.book_data: Full book data


        Returns:
        collab_filter_results: A list of the ids of the top book suggestions    
        """
        ## Attach book names to the results
        results = sorted(zip(book_names, filled_enduser_ratings), key = lambda x: x[1], reverse=True)
        collab_filter_results = []

        for item in results[self.collab_start_point+ (n_collab_returned-(n_collab_returned/count)):(self.collab_start_point + n_collab_returned)]:
            self.collab_returned = (self.collab_start_point + n_collab_returned)
            book_id = item[0]
            if self.book_data.has_key(book_id):
                if self.book_data[book_id].has_key('author'):
                    if self.book_data[book_id]['author'] not in read_authors_list:
                        collab_filter_results.append(book_id)
        return collab_filter_results



    def collaborative_filtering_predict(self, books_selected, n_collab_returned, up_votes, down_votes, count=1):
        """
        With enduser input of books and ratings, predict ratings for unread books and
        return highest predicted books.

        Args:
        books_selected: A list of the books the end-user submitted
        self.book_data: Full book library data
        db: database with users, books, and ratings
        n_collab_returned: The number of books to be returned

        Returns:
        collab_filter_results: The top n books the end-user is predicted to rate highest. 
        """

        ## Format end-user ratings into a list of dicts for the dict vectorizer
        ratings_list = self.prepare_ratings_for_dv(books_selected=books_selected, up_votes=up_votes, down_votes=down_votes)


        ## Transform end-user ratings into vector fit on full user matrix 
        ## and store the book names for later
        book_names, enduser_vector = self.dv_transform_enduser_vector(ratings_list=ratings_list)
        #print np.unique(enduser_vector)
        
        ## Transform user vector and predict ratings
        filled_enduser_ratings = self.ipca_tranform_enduser_vector(enduser_vector)
        
        ## Make a list of the authors of the books the end-user submitted 
        user_authors_list = self.create_user_authors_list(books_selected)
        
        ## Return the books the end-user is most likely to rate highest
        collab_filter_results = self.return_top_n_books(filled_enduser_ratings=filled_enduser_ratings, book_names=book_names, 
                                                        read_authors_list=user_authors_list, n_collab_returned=n_collab_returned, count=count)
        return collab_filter_results

    
    #---------------engineer keywords-----------------------------------#


    def make_aggregated_and_filtered_keyword_count_dict(keyword_conversion_dict, keywords):
        '''
        Take a keyword count dict and combine similar keywords based on keyword_conversion_dict, while filtering 
        those not included in the conversion dict. 
        '''
        new_keyword_dict = {}
        for keyword in keywords:
            if keyword in keyword_conversion_dict:
                true_label = keyword_conversion_dict[keyword]
                new_keyword_dict[true_label] = int(new_keyword_dict.get(true_label, 0)) + int(keywords[keyword])
        return new_keyword_dict


    def make_top_keyword_ranking_dict(book_id, book_data, keyword_conversion_dict):
        '''
        Make a dictionary with keywords as keys and a value of the rank of the keyword
        based on the count number

        Arguments
        book_id: the book id number (string)
        returns: a dictionary of keyword:ranking 

        '''
        ## Remove uninformative keywords and sort based on count

        filtered_keywords = self.make_aggregated_and_filtered_keyword_count_dict(keyword_conversion_dict, book_data[book_id]['keywords'])


        rank_list = sorted(filtered_keywords, key=lambda k: filtered_keywords[k]) 



        ## Pull top 40 keywords
        if len(rank_list) < 20:
            top_keywords = rank_list
        else: 
            top_keywords = rank_list[:20]

        ## Rank keywords based on order
        rank_dict = {}
        count = 0
        for keyword in top_keywords:
            rank_dict[keyword] = 20- count
            count += 1
        return rank_dict



    def check_if_ints(string):
        '''
        Check if a string is comprised of intergers
        '''
        try: 
            int(string)
            return True
        except:
            return False

    def engineer_keywords(book_data, keyword_conversion_dict):
        '''
        Replace keywords in book_data with aggregated/engineered keywords that are ranked by how often
        goodreads users associated book with them
        '''
        book_data_1 = copy.deepcopy(book_data)
        for book_id in book_data_1:
            if book_data_1[book_id].has_key('keywords') == True:
                new_keywords = make_top_keyword_ranking_dict(book_id, book_data, keyword_conversion_dict)
                book_data[book_id]['keywords'] = new_keywords
        return book_data
    
    #--------------------create "ideal" book profile----------------------------------#



    def create_book_keyword_ranking(self, collab_filter_results):
        '''
        Create a dictionary with the user's books as keys and keyword:ranking
        as values.

        Arguments
        user_ids: the user's books he is basing recommendation off of

        Returns
        a dictionary of books and their keywords and rankings 

        '''
        book_keyword_ranking_dict = {}
        for book_id in collab_filter_results:
            if self.book_data.has_key(book_id):
                keyword_rankings = self.book_data[book_id]['keywords']
                book_keyword_ranking_dict[book_id] = keyword_rankings
        return book_keyword_ranking_dict


    def user_keyword_preferences(self, books_selected):

        '''
        Take a list of book ids and make a dictionary of keywords as keys and how many 
        times each keyword is shared between books as the value

        Args: a list of book ids
        Returns: a counter dictionary of keywords and counts
        '''

        ## Make a dictionary of the top ranked keywords for each book
        book_keyword_ranking_dict = self.create_book_keyword_ranking(books_selected)

        ## return a dictionary of how many times a keyword is shared between books 
        desired_keywords = []
        for book, keywords in book_keyword_ranking_dict.items():
            for keyword, value in keywords.items():
                desired_keywords.append(keyword)
        user_keyword_preferences = Counter(desired_keywords)
        return user_keyword_preferences



    def make_user_ranking(self, keyword_preferences, features_list):
        '''
        Makes a dictionary where the keys are the most-shared keywords and the values are the rankings for them.
        A top ranking will also go to all the features the user specified in input

        Arguments
        keyword_preferences: a dictionary of keywords and how often they appear in the user's
        bookshelf
        features_list: a list of features the user specified

        Returns
        user_preference: a dictionary where the keys are keywords and the values are their ranking

        '''
        user_preference = {}
        user_preference['user'] = {}
        for i, keyword in enumerate(sorted(keyword_preferences.items(), key=lambda x : x[1], reverse=True)):
            user_preference['user'][keyword[0]] = 20 - i
        for feature in features_list:
            user_preference['user'][feature] = 20
        return user_preference

    def make_top_books_keyword_dict(self, collab_filter_results, books_returned, leftover_collab_results=[]):
        '''
        Arguments:
        collab_filter_results(list): results from collab filtering
        leftover_collab_results = results that were not previously not returned because there were less than 7 of them. 

        Turns list of top book_ids returned from ipca and creates a dictionary where:
        {book:{keyword:rank}}
        '''
        top_books_keyword_dict = {}
  
        for book_id in collab_filter_results+leftover_collab_results:
            if self.book_data[book_id].has_key('keywords') and book_id not in books_returned:
                keywords = self.book_data[book_id]['keywords']
                top_books_keyword_dict[book_id] = keywords
        return top_books_keyword_dict

    def remove_non_shared_keywords(self, top_books_keyword_dict, user_preference):
        '''
        Remove keywords from top_books if not shared with user_preference
        '''
        top_books_keyword_dict_1 = copy.deepcopy(top_books_keyword_dict)
        for book_id in top_books_keyword_dict_1:
            for keyword in top_books_keyword_dict_1[book_id]:
                if keyword not in user_preference['user'].keys():
                    del top_books_keyword_dict[book_id][keyword]
        return top_books_keyword_dict
    

    def check_if_book_has_features(self, book_id, top_books_keyword_dict, features_list):
        """
        Function to check if a book has all the features in features_list
        """
        for feature in features_list:
            if top_books_keyword_dict[book_id].has_key(feature)==False:
                return False
        return True
    
    def keep_only_if_in_feature_list(self, top_books_keyword_dict, features_list):
        '''
        Only keep books if they share a keyword with the keywords in the features_list
        '''
        revised_top_books_keyword_dict = {}
        for book_id in top_books_keyword_dict:
            #for keyword in top_books_keyword_dict[book_id]:
                #if keyword in features_list:
                    #revised_top_books_keyword_dict[book_id] = top_books_keyword_dict[book_id]
            if self.check_if_book_has_features(book_id, top_books_keyword_dict, features_list):
                revised_top_books_keyword_dict[book_id] = top_books_keyword_dict[book_id]                
        return revised_top_books_keyword_dict


    def make_book_sample_and_test_point(self, collab_filter_results, user_preference):
        """
        Turn the data of books and their keyword rankings and turn them into a sample, while 
        turning the user's preference into a point. 
        
        Arguments
        book_keyword_ranking_dict: dictionary of books as keys and keyword:rank as value
        user_preference: custom user preference based on user inmput
        
        Returns:
        sample: df with the books as rows and keywords as columns and counts as values
        point: series with keywords as columns and rank as values
        
        """
        
        df = pd.DataFrame.from_dict(collab_filter_results, orient='index')
        ## Make a dataframe of the custom book dict, to be appended to the user dataframe 
        df_to_append = pd.DataFrame.from_dict(user_preference, orient='index') 

        ## Combine the two dataframes. 
        df1 = df.append(df_to_append)
        df2 = df1.fillna(0)
        books_df = df2.ix[:-1, :]
        enduser_series = df2.ix[-1:, :]
        return books_df, enduser_series


    def apply_book_similarity_filtering(self, books_selected, collab_filter_results, 
                                        features_list, n_collab_returned, books_returned, up_votes, down_votes, leftover_collab_results=[], count=1):
        """
        Function to take end-user submitted books, find the keywords that are shared
        most among them, and are highest ranked, to determine end-user's preference.
        composition. Then, find out which books are most similar in keyword ranking composition 
        to end-user's preference.

        Args:
        books_selected (list of ints): A list of book ids
        self.book_data: A dictionary of full book data

        Returns:
        recommended_books (list of ints): List of book ids of the recommended books
        """

        ## Determine which how many times keywords are shared among end-user's 
        ## submitted books.


        user_keyword_preferences = self.user_keyword_preferences(books_selected)
        

        
        ## Create ranking based on how many times keywords are shared
        user_preference = self.make_user_ranking(user_keyword_preferences, features_list)
        


        ## Make a dict of keywords for top books and n times keyword mentioned
        top_books_keyword_dict = self.make_top_books_keyword_dict(collab_filter_results=collab_filter_results, 
                                                                  leftover_collab_results=leftover_collab_results, 
                                                                  books_returned=books_returned)
        

        
        ## Only keep those books sharing a keyword with end-users keywords
        if len(features_list) >= 1:
            top_books_keyword_dict = self.keep_only_if_in_feature_list(top_books_keyword_dict, features_list)
        
        if len(top_books_keyword_dict) < 7: 
            count += 1
            if count == 40:
                return None
            collab_filter_results = self.collaborative_filtering_predict(books_selected=books_selected, n_collab_returned=n_collab_returned+(n_collab_returned/(count-1)), 
                                                                            up_votes=up_votes, down_votes=down_votes, count=count)
            ## Run book similarity
            #print 'len top_keywords: {}'.format(len(top_books_keyword_dict))
            if len(top_books_keyword_dict) != 0:
                leftover_collab_results = top_books_keyword_dict.keys()
            else: 
                leftover_collab_results = []

            recommended_books = self.apply_book_similarity_filtering(books_selected=books_selected, 
                                                                    collab_filter_results=collab_filter_results, 
                                                                    features_list=features_list, n_collab_returned=n_collab_returned+(n_collab_returned/(count-1)), 
                                                                    leftover_collab_results=leftover_collab_results,
                                                                    up_votes=up_votes,
                                                                    down_votes=down_votes,
                                                                    books_returned=books_returned,
                                                                    count =count)

            return recommended_books

        ## Create dataframe of all books and their keyword rankings as columns
        ## Create a series of end-user's "ideal" book keyword rankings  
        books_df, enduser_series = self.make_book_sample_and_test_point(top_books_keyword_dict, user_preference)
        sample_size = len(books_df)

        ## Define clasifier
        book_neigh = NearestNeighbors(n_neighbors=sample_size, algorithm='brute', metric='matching')
        
        ## Fit on full book df
        book_neigh.fit(books_df) 

        ## Determine distance from neighbors
        book_nearest_neighbors = book_neigh.kneighbors(enduser_series)
        
        ## Put neighbors in list
        neighbors = np.ndarray.tolist(book_nearest_neighbors[1])[0]

        ## Find the sum of all neighbor distances (good for benchmarking)
        sum_distances = sum(np.ndarray.tolist(book_nearest_neighbors[0])[0])
        #print 'total sum distances: {} '.format(sum_distances)
        if self.return_distances==True:
            return sum_distances
        else: 
            print 'total sum distances: {} '.format(sum_distances)
        
        ## Return the id's for the books and place in a list
        recommended_books = [books_df.iloc[neighbor].name for neighbor in neighbors if books_df.iloc[neighbor].name not in books_returned+books_selected]


        return recommended_books[:6]

        #-------------------Tune collaborative filtering-----------------------------------#
        
    def tune_n_components(self, component_range, n_books_cross_validate):
        """
        Function to take an ipca model and sweep through a range of components,
        validating on the kneighbors distance from books input. 
        
        Arguments:
        component_range (list): 2 integers representing the beginning and end of range
        of components through which to sweep
        n_books_cross_validate: Number of books to get the distances for. 
        
        Returns:
        n_components_ranked: A ranking of different n_components based on the distances 
        of the results their models yielded. Lower rank means smaller distance.
        distances_ranked: The distances of the n_components ranked. Lower numbers mean closer distances. 

        """
        
        self.return_distances=True
        
        ## Dict with n_components and the total distance of the results form the input
        distance_dict = {}

        ## Copy the model so components can be adjusted in sweep
        ipca_model_copy = copy.deepcopy(ipca_model)
        
        random_book_keys = self.book_data.keys()
        random.shuffle(random_book_keys)
        
        ## Sweep through n_component range determine the total distance for n_books
        for n_components in range(component_range[1], component_range[0], -1):
            self.ipca_model.components_ = ipca_model_copy.components_[:n_components]
            total_distances = 0
            for book in random_book_keys[:n_books_cross_validate]:
                sum_distances = self.recommend_books(books_selected=['331690'], features_list=[])
                total_distances += sum_distances
            distance_dict[n_components] = distance_dict.get(n_components, 0) + total_distances

        ## Make a list ranking the n_components number, lower ranking posessing lower distance
        n_components_ranked = sorted(distance_dict, key=lambda x: distance_dict[x])

        ## Make a list ranking the distances, lowest first
        distances_ranked = [distance_dict[n_component] for n_component in n_components_ranked]
        return n_components_ranked, distances_ranked






if __name__ == "__main__":
    Model().main()